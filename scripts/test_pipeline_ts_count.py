"""Tests de pipeline_ts_count.py con TS sintético construido aquí (sin fixtures)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "pipeline_ts_count.py"

_spec = importlib.util.spec_from_file_location("pipeline_ts_count", SCRIPT)
tsc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tsc)

V = 0x1B
A = 0x0F


# ── builders ────────────────────────────────────────────────────────────────

def pkt(pid, payload=b"", pusi=False, afc=None, af=b"", cc=0):
    """Paquete de 188 B. payload se rellena con 0xFF; af = adaptation field entero
    (incluye su byte de longitud) cuando afc in (2, 3)."""
    if afc is None:
        afc = 1
    head = bytes([0x47, (0x40 if pusi else 0) | (pid >> 8), pid & 0xFF, (afc << 4) | (cc & 0xF)])
    body = (af if afc in (2, 3) else b"") + (payload if afc in (1, 3) else b"")
    assert len(head) + len(body) <= 188, "payload demasiado grande"
    return head + body + b"\xff" * (188 - len(head) - len(body))


def section(table_id, body, *, current=1, ext=1):
    """Sección PSI larga: header 3 + (tid-ext 2, ver/cn 1, sec 1, last 1) + body + CRC(4)."""
    inner = bytes([ext >> 8, ext & 0xFF, 0xC0 | current, 0x00, 0x00]) + body + b"\x00\x00\x00\x00"
    ln = len(inner)
    return bytes([table_id, 0xB0 | (ln >> 8), ln & 0xFF]) + inner


def pat_section(programs):
    body = b"".join(bytes([n >> 8, n & 0xFF, 0xE0 | (p >> 8), p & 0xFF]) for n, p in programs)
    return section(0x00, body)


def pmt_section(streams, *, pcr=0x100, prog_info=b"", es_info=None, prog=1, current=1):
    es_info = es_info or {}
    body = bytes([0xE0 | (pcr >> 8), pcr & 0xFF, 0xF0 | (len(prog_info) >> 8), len(prog_info) & 0xFF]) + prog_info
    for stype, epid in streams:
        info = es_info.get(epid, b"")
        body += bytes([stype, 0xE0 | (epid >> 8), epid & 0xFF, 0xF0 | (len(info) >> 8), len(info) & 0xFF]) + info
    return section(0x02, body, current=current, ext=prog)


def psi_pkt(pid, sec, cc=0):
    return pkt(pid, b"\x00" + sec, pusi=True, cc=cc)


def pes(pid, n=3):
    return [pkt(pid, b"\x00\x00\x01\xe0" + b"\x11" * 20, pusi=(i == 0), cc=i) for i in range(n)]


def standard(video_n=3, audio_n=2, streams=None):
    streams = streams or [(V, 0x100), (A, 0x101)]
    out = [psi_pkt(0, pat_section([(1, 0x1000)])), psi_pkt(0x1000, pmt_section(streams))]
    out += pes(0x100, video_n) + pes(0x101, audio_n)
    return b"".join(out)


def run(data: bytes) -> dict:
    return tsc.analyze(data)


# ── caso base ───────────────────────────────────────────────────────────────

def test_video_audio_basic():
    r = run(standard(3, 2))
    assert r == {
        "total_bytes": 188 * 7, "video_bytes": 188 * 3, "audio_bytes": 188 * 2,
        "other_bytes": 188 * 2, "pmt_seen": True, "video_pids": [0x100], "audio_pids": [0x101],
    }


def test_cli_stdin_json_output():
    p = subprocess.run([sys.executable, str(SCRIPT)], input=standard(1, 1), capture_output=True, check=True)
    out = json.loads(p.stdout)
    assert out["video_bytes"] == 188 and out["audio_bytes"] == 188 and out["pmt_seen"] is True
    assert set(out) == {"total_bytes", "video_bytes", "audio_bytes", "other_bytes",
                        "pmt_seen", "video_pids", "audio_pids"}
    assert p.stdout.count(b"\n") == 1


def test_empty_stdin():
    p = subprocess.run([sys.executable, str(SCRIPT)], input=b"", capture_output=True, check=True)
    assert json.loads(p.stdout) == {
        "total_bytes": 0, "video_bytes": 0, "audio_bytes": 0, "other_bytes": 0,
        "pmt_seen": False, "video_pids": [], "audio_pids": []}


def test_type_mapping_all_types():
    for stype in (0x01, 0x02, 0x1B, 0x24):
        r = run(standard(streams=[(stype, 0x100), (0x06, 0x101)]))
        assert r["video_bytes"] == 188 * 3 and r["audio_bytes"] == 0, hex(stype)
    for stype in (0x03, 0x04, 0x0F, 0x11):
        r = run(standard(streams=[(0x06, 0x100), (stype, 0x101)]))
        assert r["audio_bytes"] == 188 * 2 and r["video_bytes"] == 0, hex(stype)


def test_unlisted_types_are_other():
    for stype in (0x05, 0x06, 0x15, 0x81, 0x00, 0x1A, 0x25):
        r = run(standard(streams=[(stype, 0x100), (stype, 0x101)]))
        assert r["video_bytes"] == 0 and r["audio_bytes"] == 0, hex(stype)
        assert r["pmt_seen"] is True
        assert r["other_bytes"] == r["total_bytes"]


def test_multiple_video_audio_pids_sorted():
    r = run(standard(streams=[(V, 0x102), (V, 0x100), (A, 0x101)]))
    assert r["video_pids"] == [0x100, 0x102] and r["audio_pids"] == [0x101]


# ── solo uno de los dos / PMT ausente ───────────────────────────────────────

def test_only_video():
    r = run(standard(video_n=4, audio_n=0, streams=[(V, 0x100)]))
    assert r["video_bytes"] == 188 * 4 and r["audio_bytes"] == 0 and r["audio_pids"] == []


def test_only_audio():
    r = run(standard(video_n=0, audio_n=3, streams=[(A, 0x101)]))
    assert r["audio_bytes"] == 188 * 3 and r["video_bytes"] == 0 and r["video_pids"] == []


def test_pmt_absent_counts_total_only():
    data = psi_pkt(0, pat_section([(1, 0x1000)])) + b"".join(pes(0x100, 3) + pes(0x101, 2))
    r = run(data)
    assert r["pmt_seen"] is False and r["video_bytes"] == 0 and r["audio_bytes"] == 0
    assert r["total_bytes"] == 188 * 6 and r["other_bytes"] == 188 * 6


def test_pat_absent_means_pmt_not_trusted():
    data = psi_pkt(0x1000, pmt_section([(V, 0x100)])) + b"".join(pes(0x100, 2))
    r = run(data)
    assert r["pmt_seen"] is False and r["video_bytes"] == 0 and r["total_bytes"] == 188 * 3


def test_pmt_before_pat_not_parsed_but_pes_before_pmt_classified():
    # PES antes de PAT/PMT: se clasifica con el mapa final (2 pasadas)
    data = b"".join(pes(0x100, 2)) + standard(0, 0)
    r = run(data)
    assert r["video_bytes"] == 188 * 2 and r["pmt_seen"] is True


# ── PAT ─────────────────────────────────────────────────────────────────────

def test_pat_program_zero_ignored():
    # program_number 0 -> network PID (aquí 0x1000, que contiene una "PMT"): no debe usarse
    data = psi_pkt(0, pat_section([(0, 0x1000)])) + psi_pkt(0x1000, pmt_section([(V, 0x100)])) + b"".join(pes(0x100))
    r = run(data)
    assert r["pmt_seen"] is False and r["video_bytes"] == 0


def test_pat_with_network_and_two_programs():
    pat = pat_section([(0, 0x10), (1, 0x1000), (2, 0x1001)])
    data = (psi_pkt(0, pat) + psi_pkt(0x1000, pmt_section([(V, 0x100)]))
            + psi_pkt(0x1001, pmt_section([(A, 0x200)], prog=2)) + b"".join(pes(0x100, 2) + pes(0x200, 1)))
    r = run(data)
    assert r["video_pids"] == [0x100] and r["audio_pids"] == [0x200]
    assert r["video_bytes"] == 188 * 2 and r["audio_bytes"] == 188


def test_pat_not_current_ignored():
    sec = bytearray(pat_section([(1, 0x1000)]))
    sec[5] &= 0xFE  # current_next_indicator = 0
    data = psi_pkt(0, bytes(sec)) + psi_pkt(0x1000, pmt_section([(V, 0x100)])) + b"".join(pes(0x100))
    assert run(data)["pmt_seen"] is False


# ── PMT ─────────────────────────────────────────────────────────────────────

def test_pmt_program_info_and_es_info():
    sec = pmt_section([(V, 0x100), (A, 0x101)], prog_info=b"\x05\x04CUEI",
                      es_info={0x100: b"\x28\x04\x64\x00\x00\x00", 0x101: b"\x0a\x04eng\x00"})
    data = psi_pkt(0, pat_section([(1, 0x1000)])) + psi_pkt(0x1000, sec) + b"".join(pes(0x100, 2) + pes(0x101, 1))
    r = run(data)
    assert r["video_pids"] == [0x100] and r["audio_pids"] == [0x101]
    assert r["video_bytes"] == 188 * 2 and r["audio_bytes"] == 188


def test_pmt_truncated_es_loop_not_accepted():
    sec = bytearray(pmt_section([(V, 0x100)], es_info={0x100: b"\x00" * 10}))
    # es_info_length miente: dice 200 bytes
    off = 12 + 0
    sec[off + 4] = 200
    data = psi_pkt(0, pat_section([(1, 0x1000)])) + psi_pkt(0x1000, bytes(sec)) + b"".join(pes(0x100))
    r = run(data)
    assert r["pmt_seen"] is False and r["video_bytes"] == 0


def test_reserved_es_pids_ignored():
    r = run(standard(streams=[(V, 0x1FFF), (A, 0x0001), (V, 0x100)]))
    assert r["video_pids"] == [0x100] and r["audio_pids"] == []


def test_null_packets_pid_1fff_are_other():
    nulls = b"".join(pkt(0x1FFF) for _ in range(5))
    r = run(standard(2, 1) + nulls)
    assert r["total_bytes"] == 188 * (2 + 3 + 5) and r["video_bytes"] == 188 * 2
    assert r["other_bytes"] == r["total_bytes"] - 188 * 3


def test_pmt_pid_itself_never_counted_as_media():
    r = run(standard(1, 1, streams=[(V, 0x100)]))
    assert 0x1000 not in r["video_pids"] and 0 not in r["video_pids"]


# ── pointer_field, adaptation field ─────────────────────────────────────────

def test_pointer_field_nonzero():
    sec = pmt_section([(V, 0x100), (A, 0x101)])
    # pointer_field=3 con 3 bytes de relleno de la sección anterior inexistente
    pmt_pkt = pkt(0x1000, bytes([3, 0xFF, 0xFF, 0xFF]) + sec, pusi=True)
    data = psi_pkt(0, pat_section([(1, 0x1000)])) + pmt_pkt + b"".join(pes(0x100, 2) + pes(0x101, 1))
    r = run(data)
    assert r["pmt_seen"] and r["video_bytes"] == 188 * 2 and r["audio_bytes"] == 188


def test_adaptation_field_before_psi_payload():
    af = bytes([7]) + b"\x00" * 7  # adaptation_field_length=7
    pat = pkt(0, b"\x00" + pat_section([(1, 0x1000)]), pusi=True, afc=3, af=af)
    pmt = pkt(0x1000, b"\x00" + pmt_section([(V, 0x100)]), pusi=True, afc=3, af=bytes([0]))  # af_len=0
    r = run(pat + pmt + b"".join(pes(0x100, 2)))
    assert r["pmt_seen"] and r["video_bytes"] == 188 * 2


def test_adaptation_field_only_has_no_payload():
    # afc=2: lo que haya tras el adaptation field NO es payload, aunque parezca una PAT válida
    af = bytes([7]) + b"\x00" * 7
    body = af + b"\x00" + pat_section([(1, 0x1000)])
    fake = bytes([0x47, 0x40, 0x00, 0x20]) + body + b"\xff" * (184 - len(body))
    assert len(fake) == 188
    data = fake + psi_pkt(0x1000, pmt_section([(V, 0x100)])) + b"".join(pes(0x100))
    assert run(data)["pmt_seen"] is False


def test_afc_reserved_zero_has_no_payload():
    p = bytearray(psi_pkt(0, pat_section([(1, 0x1000)])))
    p[3] = (p[3] & 0x0F) | 0x00
    data = bytes(p) + psi_pkt(0x1000, pmt_section([(V, 0x100)]))
    assert run(data)["pmt_seen"] is False


def test_adaptation_field_length_overflow_ignored():
    p = bytearray(psi_pkt(0, pat_section([(1, 0x1000)])))
    p[3] = 0x30 | 0
    p[4] = 250  # longitud imposible
    data = bytes(p) + psi_pkt(0x1000, pmt_section([(V, 0x100)]))
    assert run(data)["pmt_seen"] is False  # no revienta ni inventa


# ── secciones multi-paquete ─────────────────────────────────────────────────

def _big_pmt():
    streams = [(V, 0x100), (A, 0x101)]
    info = {0x100: b"\x05" + bytes([200]) + b"x" * 200}
    return pmt_section(streams, es_info=info)


def test_pmt_spanning_two_packets_reassembled():
    sec = _big_pmt()
    assert len(sec) + 1 > 184
    first = pkt(0x1000, b"\x00" + sec[:183], pusi=True, cc=0)
    second = pkt(0x1000, sec[183:], pusi=False, cc=1)
    data = psi_pkt(0, pat_section([(1, 0x1000)])) + first + second + b"".join(pes(0x100, 2) + pes(0x101, 1))
    r = run(data)
    assert r["pmt_seen"] and r["video_bytes"] == 188 * 2 and r["audio_bytes"] == 188
    assert r["total_bytes"] == 188 * (1 + 2 + 3)


def test_pmt_spanning_incomplete_not_seen():
    sec = _big_pmt()
    first = pkt(0x1000, b"\x00" + sec[:183], pusi=True)
    data = psi_pkt(0, pat_section([(1, 0x1000)])) + first + b"".join(pes(0x100, 2))
    r = run(data)
    assert r["pmt_seen"] is False and r["video_bytes"] == 0 and r["total_bytes"] == 188 * 4


def test_continuation_without_start_discarded():
    sec = _big_pmt()
    orphan = pkt(0x1000, sec[183:], pusi=False)
    data = psi_pkt(0, pat_section([(1, 0x1000)])) + orphan + b"".join(pes(0x100))
    assert run(data)["pmt_seen"] is False


def test_pointer_field_tail_of_previous_section_completes_it():
    sec = _big_pmt()
    first = pkt(0x1000, b"\x00" + sec[:183], pusi=True)
    rest = sec[183:]
    # 2º paquete con PUSI: pointer_field = len(rest) cierra la sección previa y sigue otra PMT (pequeña)
    second = pkt(0x1000, bytes([len(rest)]) + rest + pmt_section([(V, 0x100)], prog=2), pusi=True)
    data = psi_pkt(0, pat_section([(1, 0x1000), (2, 0x1000)])) + first + second + b"".join(pes(0x100) + pes(0x101))
    r = run(data)
    assert r["pmt_seen"] and r["audio_pids"] == [0x101] and r["video_pids"] == [0x100]


# ── resincronización / basura / truncado ────────────────────────────────────

def test_garbage_prefix_resync():
    r = run(b"\x00\x01\x02" + standard(3, 2))
    assert r["total_bytes"] == 188 * 7 and r["video_bytes"] == 188 * 3


def test_garbage_prefix_with_fake_sync_byte():
    # 0x47 espurio al inicio sin otro 0x47 a +188: no debe aceptarse
    r = run(b"\x47\x47\x00" + standard(3, 2))
    assert r["total_bytes"] == 188 * 7 and r["pmt_seen"]


def test_garbage_between_packets_resync():
    ps = standard(3, 2)
    packets = [ps[i:i + 188] for i in range(0, len(ps), 188)]
    data = packets[0] + packets[1] + b"\xaa" * 37 + b"".join(packets[2:])
    r = run(data)
    assert r["total_bytes"] == 188 * 7 and r["video_bytes"] == 188 * 3 and r["audio_bytes"] == 188 * 2


def test_garbage_containing_0x47_is_not_counted():
    ps = standard(3, 2)
    packets = [ps[i:i + 188] for i in range(0, len(ps), 188)]
    junk = b"\xaa" * 10 + b"\x47" * 20
    data = packets[0] + packets[1] + junk + b"".join(packets[2:])
    r = run(data)
    assert r["total_bytes"] == 188 * 7


def test_truncated_final_packet_not_counted():
    r = run(standard(3, 2) + pkt(0x100)[:100])
    assert r["total_bytes"] == 188 * 7 and r["video_bytes"] == 188 * 3


def test_only_truncated_packet():
    assert run(pkt(0x100)[:187])["total_bytes"] == 0


def test_single_complete_packet_counts():
    assert run(pkt(0x100))["total_bytes"] == 188


def test_pure_garbage():
    r = run(bytes(range(256)) * 10)
    assert r["total_bytes"] == 0 and r["pmt_seen"] is False


def test_pure_garbage_of_0x47():
    assert run(b"\x47" * 1000)["total_bytes"] % 188 == 0  # no revienta, múltiplo de 188


# ── mutantes: los tests deben fallar si se rompe el mapeo ───────────────────

def _run_with_patched(**patch):
    saved = {k: getattr(tsc, k) for k in patch}
    try:
        for k, v in patch.items():
            setattr(tsc, k, v)
        return tsc.analyze(standard(3, 2))
    finally:
        for k, v in saved.items():
            setattr(tsc, k, v)


def test_mutants_detected_by_basic_assertions():
    """Meta-test: cada mutante del mapeo produce un resultado distinto del correcto."""
    good = tsc.analyze(standard(3, 2))
    swapped = _run_with_patched(VIDEO_TYPES=tsc.AUDIO_TYPES, AUDIO_TYPES=tsc.VIDEO_TYPES)
    assert swapped["video_bytes"] == 188 * 2 and swapped["audio_bytes"] == 188 * 3  # invertido
    assert (swapped["video_bytes"], swapped["audio_bytes"]) != (good["video_bytes"], good["audio_bytes"])
    no_video = _run_with_patched(VIDEO_TYPES=frozenset())
    assert no_video["video_bytes"] == 0 != good["video_bytes"]
    no_audio = _run_with_patched(AUDIO_TYPES=frozenset())
    assert no_audio["audio_bytes"] == 0 != good["audio_bytes"]
    all_video = _run_with_patched(VIDEO_TYPES=tsc.VIDEO_TYPES | tsc.AUDIO_TYPES)
    assert all_video["video_bytes"] == 188 * 5 != good["video_bytes"]


# ── PMT vigente REEMPLAZA la clasificación del programa (S1) ────────────────

def _two_pmts(first, second, prog_pid=0x1000, prog=1, pat=None):
    pat = pat or [(prog, prog_pid)]
    return (psi_pkt(0, pat_section(pat)) + psi_pkt(prog_pid, pmt_section(first))
            + psi_pkt(prog_pid, pmt_section(second)))


def test_later_pmt_redeclaring_pids_as_data_removes_av_classification():
    data = _two_pmts([(V, 0x100), (A, 0x101)], [(0x06, 0x100), (0x06, 0x101)])
    data += pkt(0x100) + pkt(0x101)
    r = run(data)
    assert r["video_bytes"] == 0 and r["audio_bytes"] == 0
    assert r["video_pids"] == [] and r["audio_pids"] == []
    assert r["other_bytes"] == r["total_bytes"]


def test_later_pmt_dropping_pid_removes_it():
    data = _two_pmts([(V, 0x100), (A, 0x101)], [(V, 0x100)]) + pkt(0x100) + pkt(0x101)
    r = run(data)
    assert r["video_bytes"] == 188 and r["audio_bytes"] == 0
    assert r["video_pids"] == [0x100] and r["audio_pids"] == []


def test_final_map_classifies_bytes_counted_before_the_change():
    # bytes de 0x100 ANTES de la PMT v2 (0x06): se clasifican con el mapa FINAL => other
    data = (psi_pkt(0, pat_section([(1, 0x1000)])) + psi_pkt(0x1000, pmt_section([(V, 0x100)]))
            + pkt(0x100) + psi_pkt(0x1000, pmt_section([(0x06, 0x100)])))
    assert run(data)["video_bytes"] == 0


def test_pmt_replacement_does_not_touch_other_programs():
    pat = [(1, 0x1000), (2, 0x1001)]
    data = (psi_pkt(0, pat_section(pat))
            + psi_pkt(0x1000, pmt_section([(V, 0x100)]))
            + psi_pkt(0x1001, pmt_section([(A, 0x201)], prog=2))
            + psi_pkt(0x1000, pmt_section([(0x06, 0x100)]))  # solo reemplaza el programa 1
            + pkt(0x100) + pkt(0x201))
    r = run(data)
    assert r["video_bytes"] == 0 and r["audio_bytes"] == 188
    assert r["audio_pids"] == [0x201] and r["video_pids"] == []


def test_pmt_not_current_does_not_replace():
    stale = pmt_section([(0x06, 0x100)], current=0)
    data = (psi_pkt(0, pat_section([(1, 0x1000)])) + psi_pkt(0x1000, pmt_section([(V, 0x100)]))
            + psi_pkt(0x1000, stale) + pkt(0x100))
    assert run(data)["video_bytes"] == 188
