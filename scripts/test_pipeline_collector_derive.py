"""Tests de pipeline_obs.py: derive (puro) y assemble. Todas las salidas se validan
contra schemas/admin/v1/pipeline-observation.json."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OBS = HERE / "pipeline_obs.py"
SCHEMA = json.loads((ROOT / "schemas/admin/v1/pipeline-observation.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())

_spec = importlib.util.spec_from_file_location("pipeline_obs", OBS)
obs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(obs)

SIGNALS = ["ingest.video", "ingest.audio", "ingest.data", "relay.public", "relay.announce",
           "relay.catalog", "relay.tracks", "player.http", "player.subscribe"]
AT = "2026-10-12T12:00:00Z"
LIVE1, META = "anon/live1", "anon/live1-meta"


def ts(video=0, audio=0, other=0, pmt=None, vpids=None, apids=None):
    total = video + audio + other
    pmt = (video > 0 or audio > 0) if pmt is None else pmt
    return {"total_bytes": total, "video_bytes": video, "audio_bytes": audio, "other_bytes": other,
            "pmt_seen": pmt, "video_pids": [256] if vpids is None and video else (vpids or []),
            "audio_pids": [257] if apids is None and audio else (apids or [])}


def sess(t=None, connected=True, detail=""):
    return {"connected": connected, "detail": detail, "ts": t if connected else None}


def http_ok(status=200):
    return {"curl_rc": 0, "http_status": status}


def meas(live1=None, meta=None, relay=None, player=None):
    return {"observed_at": AT, "window_seconds": 20,
            "sessions": {LIVE1: live1 if live1 is not None else sess(ts(1880, 940)),
                         META: meta if meta is not None else sess(ts(0, 0, 376, pmt=False))},
            "http": {"relay.public": relay or http_ok(), "player.http": player or http_ok()}}


def derive(m):
    out = obs.derive(m)
    assert [o["signal"] for o in out] == SIGNALS
    for o in out:
        VALIDATOR.validate(o)
        assert "no en el navegador" in o["reason"], o["reason"]
        if "metrics" in o:
            assert all(isinstance(v, int) and not isinstance(v, bool) for v in o["metrics"].values())
    return {o["signal"]: o for o in out}


def res(o):
    return {k: v["result"] for k, v in o.items()}


# ── matriz ──────────────────────────────────────────────────────────────────

def test_video_and_audio_all_pass():
    o = derive(meas(meta=sess(ts(0, 0, 564, pmt=False))))
    assert set(res(o).values()) == {"PASS"}
    assert o["ingest.video"]["metrics"] == {"bytes": 1880, "window_seconds": 20}
    assert o["ingest.audio"]["metrics"] == {"bytes": 940, "window_seconds": 20}  # nunca bytes/2
    assert o["ingest.data"]["metrics"]["bytes"] == 564
    assert o["relay.public"]["metrics"] == {"http_status": 200}
    assert o["relay.announce"]["metrics"]["bytes"] == 1880 + 940
    assert o["relay.tracks"]["metrics"] == {"bytes": 1880 + 940, "window_seconds": 20}


def test_video_only():
    o = derive(meas(live1=sess(ts(1880, 0, 188, vpids=[256], apids=[]))))
    r = res(o)
    assert r["ingest.video"] == "PASS" and r["ingest.audio"] == "FAIL"
    assert r["relay.catalog"] == "FAIL" and r["relay.tracks"] == "FAIL"
    assert r["relay.announce"] == "PASS" and r["player.subscribe"] == "PASS"
    assert o["ingest.audio"]["metrics"]["bytes"] == 0


def test_bytes_without_pmt_catalog_fail_and_media_fail():
    o = derive(meas(live1=sess(ts(0, 0, 3760, pmt=False))))
    r = res(o)
    assert r["relay.announce"] == "PASS" and r["relay.catalog"] == "FAIL"
    assert r["ingest.video"] == "FAIL" and r["ingest.audio"] == "FAIL" and r["relay.tracks"] == "FAIL"


def test_connected_zero_bytes_all_fail():
    o = derive(meas(live1=sess(ts()), meta=sess(ts())))
    r = res(o)
    for s in ("ingest.video", "ingest.audio", "ingest.data", "relay.announce", "relay.catalog",
              "relay.tracks", "player.subscribe"):
        assert r[s] == "FAIL", s
    assert "sin bytes en anon/live1-meta" in o["ingest.data"]["reason"].lower()
    assert r["relay.public"] == "PASS" and r["player.http"] == "PASS"


def test_not_connected_everything_dependent_unknown():
    bad = sess(connected=False, detail="el cliente informó error de conexión/DNS/TLS/imagen")
    o = derive(meas(live1=bad, meta=bad))
    r = res(o)
    for s in ("ingest.video", "ingest.audio", "ingest.data", "relay.announce", "relay.catalog",
              "relay.tracks", "player.subscribe"):
        assert r[s] == "UNKNOWN", s
        assert "metrics" not in o[s]
    assert r["relay.public"] == "PASS" and r["player.http"] == "PASS"  # HTTP es independiente


def test_only_meta_not_connected():
    o = derive(meas(meta=sess(connected=False, detail="x")))
    assert res(o)["ingest.data"] == "UNKNOWN" and res(o)["ingest.video"] == "PASS"


def test_real_case_today_data_fail_live1_pass():
    o = derive(meas(live1=sess(ts(5000, 1000)), meta=sess(ts())))
    r = res(o)
    assert r["ingest.data"] == "FAIL" and r["ingest.video"] == "PASS" and r["ingest.audio"] == "PASS"
    assert r["relay.announce"] == "PASS" and r["relay.catalog"] == "PASS"
    assert r["relay.tracks"] == "PASS" and r["player.subscribe"] == "PASS"


@pytest.mark.parametrize("signal,url", [("relay.public", "/api/cert-hash"), ("player.http", "/player/")])
def test_http_matrix(signal, url):
    key = "relay" if signal == "relay.public" else "player"
    o = derive(meas(**{key: http_ok(200)}))[signal]
    assert o["result"] == "PASS" and o["metrics"] == {"http_status": 200} and url in o["reason"]
    for code in (404, 500, 301, 403):
        o = derive(meas(**{key: http_ok(code)}))[signal]
        assert o["result"] == "FAIL" and o["metrics"] == {"http_status": code}
    for bad in ({"curl_rc": 28, "http_status": None}, {"curl_rc": 7, "http_status": 0},
                {"curl_rc": 28, "http_status": 200},   # rc manda aunque haya código
                {"curl_rc": None, "http_status": None}, {"curl_rc": 0, "http_status": 0},
                {"curl_rc": 0, "http_status": None}, {"curl_rc": "0", "http_status": 200}):
        o = derive(meas(**{key: bad}))[signal]
        assert o["result"] == "UNKNOWN" and "metrics" not in o, bad


@pytest.mark.parametrize("garbage", [None, [], "x", 5, {}, {"sessions": 5}, {"sessions": {LIVE1: 7}},
                                     {"sessions": {LIVE1: {"connected": True, "ts": {"total_bytes": -1}}}},
                                     {"sessions": {LIVE1: {"connected": True, "ts": {"total_bytes": True}}}},
                                     {"http": {"relay.public": "x"}}])
def test_garbage_input_all_unknown(garbage):
    o = derive(garbage)
    assert set(res(o).values()) == {"UNKNOWN"}


def test_connected_true_with_invalid_ts_is_unknown_not_pass():
    m = meas(live1={"connected": True, "ts": {"total_bytes": 10, "video_bytes": 10}})
    assert res(derive(m))["ingest.video"] == "UNKNOWN"


# ── reason: comillas, backslash, saltos, unicode, truncado ──────────────────

@pytest.mark.parametrize("detail", ['dice "hola"', "ruta C:\\x\\y", "línea1\nlínea2\r\n\ttab",
                                    "ñandú ✓ 日本語 \u2028 \x00 \x1b[31m", "'; DROP", "x" * 1000])
def test_hostile_detail_stays_valid_single_line(detail):
    bad = sess(connected=False, detail=detail)
    m = meas(live1=bad, meta=bad)
    proc = subprocess.run([sys.executable, str(OBS), "derive"], input=json.dumps(m),
                          capture_output=True, text=True, check=True)
    lines = proc.stdout.splitlines()
    assert len(lines) == 9
    for line in lines:
        o = json.loads(line)  # cada línea es un JSON completo
        VALIDATOR.validate(o)
        assert len(o["reason"]) <= 300 and o["reason"].strip()
    assert json.loads(lines[0])["reason"].endswith("no en el navegador.")


def test_reason_over_300_truncated():
    long = obs._cap("y" * 1000)
    assert len(long) == 300 and long.endswith("…")
    assert obs._cap("a" * 300) == "a" * 300


# ── honestidad ──────────────────────────────────────────────────────────────

def test_never_pass_without_evidence():
    cases = [meas(live1=sess(ts()), meta=sess(ts())),
             meas(live1=sess(ts(0, 0, 9400, pmt=False))),
             meas(live1=sess(connected=False, detail="x"), meta=sess(connected=False, detail="x")),
             {}]
    for m in cases:
        o = derive(m)
        for s in ("ingest.video", "ingest.audio"):
            if o[s]["result"] == "PASS":
                raise AssertionError(f"PASS sin bytes de {s}")
        assert o["relay.tracks"]["result"] != "PASS"
        assert o["ingest.data"]["result"] != "PASS" or m["sessions"][META]["ts"]["total_bytes"] > 0


def test_zero_bytes_must_not_pass_any_signal():
    o = derive(meas(live1=sess(ts()), meta=sess(ts())))
    assert [s for s, v in res(o).items() if v == "PASS" and s not in ("relay.public", "player.http")] == []


def test_pass_metrics_bytes_positive():
    for s, v in derive(meas()).items():
        if v["result"] == "PASS" and s not in ("relay.public", "player.http"):
            assert v["metrics"]["bytes"] > 0, s


# ── session_connected / assemble ────────────────────────────────────────────

T = ts(1880, 940)


@pytest.mark.parametrize("stderr", [
    "Error: Connection refused", "dns error: failed to lookup address", "TLS handshake failed",
    "certificate verify failed", "operation timed out", "Unable to find image 'moqdev/moq:0.12.7' locally",
    "pull access denied for moqdev/moq", "Name or service not known",
    "docker: Error response from daemon: x", "Cannot connect to the Docker daemon at unix:///x"])
def test_connection_errors_in_stderr_mean_not_connected(stderr):
    ok, detail = obs.session_connected(True, 124, stderr, T)
    assert ok is False and detail


def test_session_connected_cases():
    assert obs.session_connected(True, 124, "INFO connected\n", T) == (True, "")
    assert obs.session_connected(True, 0, "", T)[0] is True
    assert obs.session_connected(False, 124, "", T)[0] is False       # docker ausente
    assert obs.session_connected(True, None, "", T)[0] is False       # sin rc
    for rc in (125, 126, 127):
        assert obs.session_connected(True, rc, "", T)[0] is False
    assert obs.session_connected(True, 1, "", ts())[0] is False       # error y 0 bytes
    assert obs.session_connected(True, 1, "", T)[0] is True           # error pero llegaron bytes
    assert obs.session_connected(True, 124, "", None)[0] is False
    assert obs.session_connected(True, 124, "", {"total_bytes": 1})[0] is False


def test_assemble_reads_dir_and_stderr_never_counted(tmp_path):
    d = tmp_path
    (d / "docker_available").write_text("1\n")
    (d / "live1.rc").write_text("124\n")
    (d / "live1.stderr").write_text("A" * 100000)  # stderr enorme: no son bytes de datos
    (d / "live1.ts.json").write_text(json.dumps(ts()))
    (d / "meta.rc").write_text("124\n")
    (d / "meta.stderr").write_text("")
    (d / "meta.ts.json").write_text(json.dumps(ts(0, 0, 188, pmt=False)))
    (d / "relay_public.curl_rc").write_text("0\n")
    (d / "relay_public.http_code").write_text("200\n")
    (d / "player_http.curl_rc").write_text("28\n")
    (d / "player_http.http_code").write_text("000\n")
    m = obs.assemble(d)
    assert m["sessions"][LIVE1]["connected"] is True and m["sessions"][LIVE1]["ts"]["total_bytes"] == 0
    o = derive(m)
    assert o["ingest.video"]["result"] == "FAIL" and o["ingest.data"]["result"] == "PASS"
    assert o["relay.public"]["result"] == "PASS" and o["player.http"]["result"] == "UNKNOWN"


def test_assemble_missing_files_all_unknown(tmp_path):
    o = derive(obs.assemble(tmp_path))
    assert set(res(o).values()) == {"UNKNOWN"}


def test_assemble_garbage_files_unknown(tmp_path):
    (tmp_path / "docker_available").write_text("1")
    for tag in ("live1", "meta"):
        (tmp_path / f"{tag}.rc").write_text("abc")
        (tmp_path / f"{tag}.ts.json").write_text("{not json")
    o = derive(obs.assemble(tmp_path))
    assert set(res(o).values()) == {"UNKNOWN"}


def test_cli_derive_invalid_stdin_still_nine_lines():
    p = subprocess.run([sys.executable, str(OBS), "derive"], input="no es json", capture_output=True, text=True)
    assert p.returncode == 0 and len(p.stdout.splitlines()) == 9
    assert all(json.loads(l)["result"] == "UNKNOWN" for l in p.stdout.splitlines())


# ── métricas exactas de las 9 señales (valores calculados a mano) ───────────

def test_exact_metrics_all_nine_signals_pass():
    # live1: vídeo 1880 + audio 940 + otros 188 = 3008 B; meta: 376 B; ventana 20 s
    o = derive(meas(live1=sess(ts(1880, 940, 188)), meta=sess(ts(0, 0, 376, pmt=False))))
    assert {k: v["result"] for k, v in o.items()} == {s: "PASS" for s in SIGNALS}
    assert {k: v["metrics"] for k, v in o.items()} == {
        "ingest.video": {"bytes": 1880, "window_seconds": 20},
        "ingest.audio": {"bytes": 940, "window_seconds": 20},
        "ingest.data": {"bytes": 376, "window_seconds": 20},
        "relay.public": {"http_status": 200},
        "relay.announce": {"bytes": 3008, "window_seconds": 20},
        "relay.catalog": {"bytes": 3008, "window_seconds": 20},
        "relay.tracks": {"bytes": 2820, "window_seconds": 20},
        "player.http": {"http_status": 200},
        "player.subscribe": {"bytes": 3008, "window_seconds": 20},
    }


def test_exact_metrics_video_only_fail_paths():
    # solo vídeo 1880 + otros 188 = 2068 B, sin audio: audio/catalog/tracks FAIL
    o = derive(meas(live1=sess(ts(1880, 0, 188, vpids=[256], apids=[]))))
    assert o["ingest.audio"]["metrics"] == {"bytes": 0, "window_seconds": 20}
    assert o["relay.catalog"]["metrics"] == {"bytes": 2068, "window_seconds": 20}
    assert o["relay.tracks"]["metrics"] == {"bytes": 1880, "window_seconds": 20}
    assert o["relay.announce"]["metrics"] == {"bytes": 2068, "window_seconds": 20}
    assert o["player.subscribe"]["metrics"] == {"bytes": 2068, "window_seconds": 20}


def test_exact_metrics_zero_bytes_fail_paths():
    o = derive(meas(live1=sess(ts()), meta=sess(ts())))
    for s in ("ingest.video", "ingest.audio", "ingest.data", "relay.announce", "relay.catalog",
              "relay.tracks", "player.subscribe"):
        assert o[s]["metrics"] == {"bytes": 0, "window_seconds": 20}, s


def test_window_seconds_is_fixed_production_window_not_taken_from_input():
    m = meas()
    m["window_seconds"] = 7  # entrada no confiable: la ventana real es la constante de producción
    o = derive(m)
    for s in ("ingest.video", "ingest.audio", "ingest.data", "relay.announce", "relay.catalog",
              "relay.tracks", "player.subscribe"):
        assert o[s]["metrics"]["window_seconds"] == 20, s
