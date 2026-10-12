#!/usr/bin/env python3
"""
Derivación de observaciones del pipeline — solo TRANSPORTE (#214).

Dos subcomandos, para que el colector bash solo MIDA y no construya JSON:

  pipeline_obs.py assemble --dir DIR   (I/O) lee los ficheros que dejó el colector
                                        y escribe el JSON de mediciones por stdout.
  pipeline_obs.py derive               (PURO) JSON de mediciones por stdin ->
                                        9 líneas JSON (una por señal) por stdout.

Siempre se emiten las 9 señales, aunque la entrada sea basura (-> UNKNOWN).
La máquina NUNCA afirma calidad audiovisual: solo llegada de bytes/HTTP.

Criterio de "conectó" (sesión moq, ver `session_connected`): docker arrancó
(disponible y rc no 125/126/127), stderr no contiene errores de conexión / DNS /
TLS / refused / timeout de conexión / "unable to find image" / "pull access",
la medición TS existe y, si el cliente salió con error (rc no en {0,124,130,137,143}),
solo si llegaron bytes. Si no conectó: señales dependientes UNKNOWN.

Formato de mediciones:
{
 "observed_at": "...Z" (opcional), "window_seconds": 20,
 "sessions": {"anon/live1": {"connected": bool, "detail": str, "ts": {conteos} | null},
              "anon/live1-meta": {...}},
 "http": {"relay.public": {"curl_rc": int|null, "http_status": int|null},
          "player.http": {...}}
}
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

SIGNALS = (
    "ingest.video", "ingest.audio", "ingest.data",
    "relay.public", "relay.announce", "relay.catalog", "relay.tracks",
    "player.http", "player.subscribe",
)
BROADCAST_MEDIA = "anon/live1"
BROADCAST_META = "anon/live1-meta"
SESSION_TAGS = {"live1": BROADCAST_MEDIA, "meta": BROADCAST_META}
HTTP_FILES = {"relay.public": "relay_public", "player.http": "player_http"}
WINDOW_SECONDS = 20
REASON_MAX = 300
SUFFIX = " Medido en el relay público con el cliente CLI oficial, no en el navegador."
SUFFIX_HTTP = " Medido con curl en el relay público desde el host, no en el navegador."
SUFFIX_PLAYER = SUFFIX + " Suscripción con cliente CLI oficial, no el navegador del player."

TS_KEYS = ("total_bytes", "video_bytes", "audio_bytes", "other_bytes")
OK_RCS = {0, 124, 130, 137, 143}
START_FAIL_RCS = {125, 126, 127}
CONNECT_ERROR_RE = re.compile(
    r"refused|failed to connect|could not connect|unable to connect|connection error|"
    r"error connecting|\bdns\b|lookup|no such host|name or service not known|"
    r"temporary failure in name resolution|\btls\b|certificate|handshake|"
    r"timed out|timeout|deadline has elapsed|unable to find image|pull access|"
    r"cannot connect to the docker daemon|error response from daemon|"
    r"network is unreachable|no route to host",
    re.IGNORECASE,
)
ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cap(text: str) -> str:
    text = str(text)
    return text if len(text) <= REASON_MAX else text[: REASON_MAX - 1] + "…"


def _obs(signal, result, reason, observed_at, **metrics) -> dict:
    out = {"signal": signal, "result": result, "observed_at": observed_at, "reason": _cap(reason)}
    metrics = {k: v for k, v in metrics.items() if _is_int(v)}
    if metrics:
        out["metrics"] = metrics
    return out


def _unknown(signal, observed_at, why, suffix=SUFFIX) -> dict:
    return _obs(signal, "UNKNOWN", f"No medible: {why}.{suffix}", observed_at)


# ── conexión ────────────────────────────────────────────────────────────────

def session_connected(docker_available, rc, stderr_text, ts):
    """-> (connected: bool, detail: str). detail es texto fijo (nunca stderr crudo)."""
    if not docker_available:
        return False, "docker ausente en el host"
    if not _is_int(rc):
        return False, "sesión moq no ejecutada"
    if rc in START_FAIL_RCS:
        return False, "docker no pudo arrancar el cliente"
    if CONNECT_ERROR_RE.search(stderr_text or ""):
        return False, "el cliente informó error de conexión/DNS/TLS/imagen"
    if _ts_valid(ts) is None:
        return False, "medición TS no disponible"
    if rc not in OK_RCS and ts["total_bytes"] == 0:
        return False, "el cliente terminó con error sin recibir datos"
    return True, ""


def _ts_valid(ts):
    if not isinstance(ts, dict):
        return None
    for k in TS_KEYS:
        if not _is_int(ts.get(k)) or ts[k] < 0:
            return None
    if not isinstance(ts.get("pmt_seen"), bool):
        return None
    for k in ("video_pids", "audio_pids"):
        v = ts.get(k)
        if not isinstance(v, list) or not all(_is_int(x) for x in v):
            return None
    return ts


# ── derivación ──────────────────────────────────────────────────────────────

def _session(m, broadcast):
    """-> ('ok', ts) | ('unknown', detail)"""
    try:
        s = m["sessions"][broadcast]
        if s.get("connected") is not True:
            d = s.get("detail")
            return "unknown", d[:120] if isinstance(d, str) and d else "sesión moq no conectada"
        ts = _ts_valid(s.get("ts"))
        if ts is None:
            return "unknown", "medición TS inválida"
        return "ok", ts
    except Exception:
        return "unknown", "sesión moq sin medición"


def _http(m, signal, url_label, at):
    try:
        h = m["http"][signal]
        rc, status = h.get("curl_rc"), h.get("http_status")
    except Exception:
        return _unknown(signal, at, f"sin medición HTTP de {url_label}", SUFFIX_HTTP)
    if not _is_int(rc):
        return _unknown(signal, at, f"sin medición HTTP de {url_label}", SUFFIX_HTTP)
    if rc != 0:
        return _unknown(signal, at, f"curl falló (rc={rc}) al pedir {url_label}", SUFFIX_HTTP)
    if not _is_int(status) or not 100 <= status <= 599:
        return _unknown(signal, at, f"código HTTP inválido al pedir {url_label}", SUFFIX_HTTP)
    result = "PASS" if status == 200 else "FAIL"
    return _obs(signal, result, f"{url_label} respondió HTTP {status}.{SUFFIX_HTTP}", at, http_status=status)


def derive(measurements) -> list[dict]:
    m = measurements if isinstance(measurements, dict) else {}
    at = m.get("observed_at")
    at = at if isinstance(at, str) and ISO_RE.match(at) else _now()
    w = WINDOW_SECONDS
    out: dict[str, dict] = {}

    kind, media = _session(m, BROADCAST_MEDIA)
    if kind == "ok":
        ts = media
        v, a, t = ts["video_bytes"], ts["audio_bytes"], ts["total_bytes"]
        out["ingest.video"] = (
            _obs("ingest.video", "PASS", f"Llegaron {v} bytes de vídeo en {BROADCAST_MEDIA} en {w} s.{SUFFIX}", at, bytes=v, window_seconds=w)
            if v > 0 else
            _obs("ingest.video", "FAIL", f"Sesión conectada pero 0 bytes de vídeo en {BROADCAST_MEDIA} en {w} s.{SUFFIX}", at, bytes=0, window_seconds=w))
        out["ingest.audio"] = (
            _obs("ingest.audio", "PASS", f"Llegaron {a} bytes de audio en {BROADCAST_MEDIA} en {w} s.{SUFFIX}", at, bytes=a, window_seconds=w)
            if a > 0 else
            _obs("ingest.audio", "FAIL", f"Sesión conectada pero 0 bytes de audio en {BROADCAST_MEDIA} en {w} s.{SUFFIX}", at, bytes=0, window_seconds=w))
        out["relay.announce"] = (
            _obs("relay.announce", "PASS", f"{BROADCAST_MEDIA} entregó {t} bytes en {w} s.{SUFFIX}", at, bytes=t, window_seconds=w)
            if t > 0 else
            _obs("relay.announce", "FAIL", f"Sesión conectada pero {BROADCAST_MEDIA} no entregó bytes en {w} s.{SUFFIX}", at, bytes=0, window_seconds=w))
        has_catalog = ts["pmt_seen"] and len(ts["video_pids"]) >= 1 and len(ts["audio_pids"]) >= 1
        if has_catalog:
            out["relay.catalog"] = _obs("relay.catalog", "PASS", f"El flujo de {BROADCAST_MEDIA} declara PMT con vídeo y audio.{SUFFIX}", at, bytes=t, window_seconds=w)
        elif t > 0:
            out["relay.catalog"] = _obs("relay.catalog", "FAIL", f"Llegaron bytes pero sin PMT con vídeo y audio (pmt_seen={str(ts['pmt_seen']).lower()}).{SUFFIX}", at, bytes=t, window_seconds=w)
        else:
            out["relay.catalog"] = _obs("relay.catalog", "FAIL", f"Sesión conectada pero sin bytes ni PMT en {BROADCAST_MEDIA}.{SUFFIX}", at, bytes=0, window_seconds=w)
        out["relay.tracks"] = (
            _obs("relay.tracks", "PASS", f"Llegaron bytes de vídeo ({v}) y de audio ({a}) en {w} s.{SUFFIX}", at, bytes=v + a, window_seconds=w)
            if v > 0 and a > 0 else
            _obs("relay.tracks", "FAIL", f"Faltan tracks: bytes de vídeo={v}, de audio={a} en {w} s.{SUFFIX}", at, bytes=v + a, window_seconds=w))
        out["player.subscribe"] = (
            _obs("player.subscribe", "PASS", f"La suscripción recibió {t} bytes en {w} s.{SUFFIX_PLAYER}", at, bytes=t, window_seconds=w)
            if t > 0 else
            _obs("player.subscribe", "FAIL", f"Suscripción conectada pero sin bytes en {w} s.{SUFFIX_PLAYER}", at, bytes=0, window_seconds=w))
    else:
        for sig in ("ingest.video", "ingest.audio", "relay.announce", "relay.catalog", "relay.tracks", "player.subscribe"):
            out[sig] = _unknown(sig, at, f"{media} ({BROADCAST_MEDIA})")

    kind, meta = _session(m, BROADCAST_META)
    if kind == "ok":
        t = meta["total_bytes"]
        out["ingest.data"] = (
            _obs("ingest.data", "PASS", f"Llegaron {t} bytes en {BROADCAST_META} en {w} s.{SUFFIX}", at, bytes=t, window_seconds=w)
            if t > 0 else
            _obs("ingest.data", "FAIL", f"Sin bytes en {BROADCAST_META} (sesión conectada) en {w} s.{SUFFIX}", at, bytes=0, window_seconds=w))
    else:
        out["ingest.data"] = _unknown("ingest.data", at, f"{meta} ({BROADCAST_META})")

    out["relay.public"] = _http(m, "relay.public", "https://wow.teremoq.com/api/cert-hash", at)
    out["player.http"] = _http(m, "player.http", "https://wow.teremoq.com/player/", at)
    return [out[s] for s in SIGNALS]


# ── assemble (I/O) ──────────────────────────────────────────────────────────

def _read(path: Path):
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _read_int(path: Path):
    t = _read(path)
    try:
        return int(t.strip()) if t is not None else None
    except ValueError:
        return None


def assemble(d: Path) -> dict:
    docker_ok = (_read(d / "docker_available") or "").strip() == "1"
    sessions = {}
    for tag, broadcast in SESSION_TAGS.items():
        ts = None
        raw = _read(d / f"{tag}.ts.json")
        if raw and raw.strip():
            try:
                ts = json.loads(raw)
            except ValueError:
                ts = None
        ok, detail = session_connected(
            docker_ok, _read_int(d / f"{tag}.rc"), _read(d / f"{tag}.stderr"), ts)
        sessions[broadcast] = {"connected": ok, "detail": detail, "ts": ts if ok else None}
    http = {}
    for signal, stem in HTTP_FILES.items():
        code = _read_int(d / f"{stem}.http_code")
        http[signal] = {"curl_rc": _read_int(d / f"{stem}.curl_rc"),
                        "http_status": code if code else None}
    return {"observed_at": _now(), "window_seconds": WINDOW_SECONDS,
            "sessions": sessions, "http": http}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("derive")
    a = sub.add_parser("assemble")
    a.add_argument("--dir", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "assemble":
        print(json.dumps(assemble(Path(args.dir))))
        return 0
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        data = {}
    for o in derive(data):
        print(json.dumps(o))
    return 0


if __name__ == "__main__":
    sys.exit(main())
