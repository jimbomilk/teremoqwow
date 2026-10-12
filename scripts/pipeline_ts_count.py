#!/usr/bin/env python3
"""
Contador de bytes MPEG-TS por tipo de stream — solo TRANSPORTE (#214).

Lee MPEG-TS de stdin y escribe un único JSON:
  {"total_bytes", "video_bytes", "audio_bytes", "other_bytes",
   "pmt_seen", "video_pids", "audio_pids"}

Qué hace (y nada más): sincroniza paquetes de 188 B, lee PAT -> PMT para saber
qué PIDs son vídeo/audio según stream_type y suma 188 B por paquete. NUNCA
decodifica, ni mira PES/ES, ni evalúa calidad.

Decisiones documentadas:
- Sincronía: un 0x47 solo cuenta como inicio de paquete si hay otro 0x47 a +188
  (o si el paquete termina exactamente al final de los datos). Los bytes de
  basura/desalineación NO se cuentan. Un paquete truncado final no se cuenta.
- Clasificación en 2 pasadas: los bytes se acumulan por PID y se clasifican con
  el mapa final PAT/PMT (los paquetes anteriores a la PMT también cuentan).
- PMT vigente: la última PMT aceptada (current_next=1, por orden de llegada) de
  un program_number REEMPLAZA la clasificación de los PIDs de ese programa; PIDs
  que desaparecen o pasan a tipo no AV dejan de ser vídeo/audio. No toca los PIDs
  de otros programas. Coherente con las dos pasadas: TODOS los bytes de un PID,
  también los anteriores al cambio, se clasifican con el mapa FINAL.
- Secciones PSI > 1 paquete: SÍ se reensamblan por PID (pointer_field y
  continuación sin PUSI). No se verifica CRC32 ni continuity_counter: el
  objetivo es transporte, no validación de conformidad.
- Una sección PMT solo se acepta si su PID fue anunciado por una PAT
  (program_number 0 = red, ignorado). Sin PAT => pmt_seen=false y video/audio=0.
- Entradas ES con PID reservado (<0x10 o 0x1FFF) se ignoran.
- video_pids/audio_pids = PIDs declarados en la PMT (hayan o no recibido bytes).
- Tipos vídeo {0x01,0x02,0x1b,0x24}; audio {0x03,0x04,0x0f,0x11}; el resto = other.
"""
from __future__ import annotations

import json
import sys

PACKET = 188
SYNC = 0x47
VIDEO_TYPES = frozenset({0x01, 0x02, 0x1B, 0x24})
AUDIO_TYPES = frozenset({0x03, 0x04, 0x0F, 0x11})
MAX_SECTION_BUF = 4096 + 188  # una sección PSI mide como mucho 4096 B


def iter_packets(data: bytes):
    """Genera paquetes de 188 B alineados, resincronizando tras basura.

    Sin sincronía previa, un 0x47 en i solo es inicio de paquete si hay otro
    0x47 en i+188 (o el paquete acaba justo al final de los datos). Con
    sincronía (el paquete anterior era válido y contiguo) basta el 0x47 en i.
    Limitación: basura que empiece justo en un límite de paquete con 0x47 se
    tomaría por un paquete; después se pierde sincronía y se recupera.
    """
    n = len(data)
    i = 0
    synced = False
    while i + PACKET <= n:
        if data[i] == SYNC:
            nxt = i + PACKET
            if synced or nxt == n or data[nxt] == SYNC:
                yield data[i:nxt]
                i = nxt
                synced = True
                continue
        synced = False
        i += 1


def _payload(pkt: bytes):
    afc = (pkt[3] >> 4) & 0x3
    if afc in (0, 2):  # reservado / solo adaptation field
        return None
    if afc == 1:
        return pkt[4:]
    start = 5 + pkt[4]  # afc == 3: adaptation field + payload
    if start > PACKET:
        return None
    return pkt[start:]


class _Psi:
    def __init__(self):
        self.buf: dict[int, bytearray] = {}
        self.pmt_pids: set[int] = set()
        self.pmt_seen = False
        self.prog_kind: dict[int, dict[int, str]] = {}  # program_number -> {pid: kind}

    def feed(self, pid: int, pusi: bool, payload: bytes):
        buf = self.buf.get(pid)
        if pusi:
            if not payload:
                return
            pointer = payload[0]
            if 1 + pointer > len(payload):
                self.buf.pop(pid, None)
                return
            if buf:  # cola de la sección anterior
                buf.extend(payload[1:1 + pointer])
                self._drain(buf, pid)
            buf = bytearray(payload[1 + pointer:])
            self.buf[pid] = buf
        else:
            if not buf:
                return  # continuación sin inicio visto: descartar
            buf.extend(payload)
        self._drain(buf, pid)

    def _drain(self, buf: bytearray, pid: int):
        while buf:
            if buf[0] == 0xFF:  # stuffing
                buf.clear()
                return
            if len(buf) < 3:
                return
            total = 3 + (((buf[1] & 0x0F) << 8) | buf[2])
            if len(buf) < total:
                if len(buf) > MAX_SECTION_BUF:
                    buf.clear()
                return
            section = bytes(buf[:total])
            del buf[:total]
            self._section(pid, section)

    def _section(self, pid: int, s: bytes):
        table_id = s[0]
        if len(s) < 12 or not (s[1] & 0x80) or not (s[5] & 0x01):
            return  # sin syntax indicator o no vigente (current_next=0)
        if pid == 0 and table_id == 0x00:
            end = len(s) - 4  # sin CRC32
            for off in range(8, end - 3, 4):
                program = (s[off] << 8) | s[off + 1]
                ppid = ((s[off + 2] & 0x1F) << 8) | s[off + 3]
                if program != 0:
                    self.pmt_pids.add(ppid)
        elif pid in self.pmt_pids and table_id == 0x02:
            self._pmt(s)

    def _pmt(self, s: bytes):
        end = len(s) - 4  # sin CRC32
        off = 12 + (((s[10] & 0x0F) << 8) | s[11])  # tras program_info
        found: dict[int, str] = {}
        while off + 5 <= end:
            stype = s[off]
            epid = ((s[off + 1] & 0x1F) << 8) | s[off + 2]
            off += 5 + (((s[off + 3] & 0x0F) << 8) | s[off + 4])
            if off > end:
                return  # PMT malformada: no aceptar nada de ella
            if epid < 0x10 or epid == 0x1FFF:
                continue
            if stype in VIDEO_TYPES:
                found[epid] = "video"
            elif stype in AUDIO_TYPES:
                found[epid] = "audio"
        if off > end:
            return  # program_info_length fuera de la sección
        self.pmt_seen = True
        self.prog_kind[(s[3] << 8) | s[4]] = found  # la PMT vigente REEMPLAZA a la del programa

    @property
    def pid_kind(self) -> dict[int, str]:
        merged: dict[int, str] = {}
        for found in self.prog_kind.values():
            merged.update(found)
        return merged


def analyze(data: bytes) -> dict:
    psi = _Psi()
    per_pid: dict[int, int] = {}
    total = 0
    for pkt in iter_packets(data):
        total += PACKET
        pid = ((pkt[1] & 0x1F) << 8) | pkt[2]
        per_pid[pid] = per_pid.get(pid, 0) + PACKET
        if pid == 0 or pid in psi.pmt_pids:
            payload = _payload(pkt)
            if payload is not None:
                psi.feed(pid, bool(pkt[1] & 0x40), payload)
    video = audio = 0
    vpids, apids = [], []
    for pid, nbytes in per_pid.items():
        kind = psi.pid_kind.get(pid)
        if kind == "video":
            video += nbytes
        elif kind == "audio":
            audio += nbytes
    for pid, kind in psi.pid_kind.items():  # PIDs declarados en la PMT
        (vpids if kind == "video" else apids).append(pid)
    return {
        "total_bytes": total,
        "video_bytes": video,
        "audio_bytes": audio,
        "other_bytes": total - video - audio,
        "pmt_seen": psi.pmt_seen,
        "video_pids": sorted(vpids),
        "audio_pids": sorted(apids),
    }


def main() -> int:
    data = sys.stdin.buffer.read()
    sys.stdout.write(json.dumps(analyze(data)) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
