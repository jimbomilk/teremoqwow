"""
Punto 4 — pipeline_ingest.py: matriz acepta/rechaza comparada con el schema REAL
pipeline-observation.json vía jsonschema, y comportamiento de la CLI (exit codes).

Run: python3 -m pytest admin/test_pipeline_ingest.py -q
"""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
from datetime import timedelta

import pytest

import test_pipeline_support as S
from test_pipeline_fakeredis import FakeRedis

import pipeline_api as A
import pipeline_ingest as I

NOW = S.T0


def ok_obs(**over):
    o = {"signal": "ingest.video", "result": "PASS", "observed_at": S.iso(NOW), "reason": "hubo datos"}
    o.update(over)
    return o


def expected_accept(obs) -> bool:
    """Oráculo: el schema real + la regla del propio schema (descripción) de >60 s en el futuro."""
    if S.schema_errors(S.OBSERVATION_ID, obs):
        return False
    at = obs["observed_at"]
    from pipeline_state import parse_rfc3339
    return parse_rfc3339(at) <= NOW + timedelta(seconds=60)


def rm(key):
    o = ok_obs()
    del o[key]
    return o


CASES = {
    # ── válidas ──
    "minimal": ok_obs(),
    "result FAIL": ok_obs(result="FAIL"),
    "result UNKNOWN": ok_obs(result="UNKNOWN"),
    **{f"signal {s}": ok_obs(signal=s) for s in S.ALL_SIGNALS},
    "metrics {}": ok_obs(metrics={}),
    "metrics full": ok_obs(metrics={"bytes": 0, "objects": 0, "window_seconds": 1, "http_status": 100}),
    "metrics max": ok_obs(metrics={"bytes": 10**12, "objects": 10**9, "window_seconds": 3600, "http_status": 599}),
    "metrics float integral 5.0": ok_obs(metrics={"bytes": 5.0}),
    "reason len 1": ok_obs(reason="x"),
    "reason len 300": ok_obs(reason="x" * 300),
    "reason unicode 300": ok_obs(reason="ñ" * 300),
    "observed_at offset": ok_obs(observed_at="2026-10-12T14:00:00+02:00"),
    "observed_at fraction": ok_obs(observed_at="2026-10-12T12:00:00.123456Z"),
    "observed_at future +60": ok_obs(observed_at=S.iso(NOW + timedelta(seconds=60))),
    "observed_at old (stale, not invalid)": ok_obs(observed_at="2001-01-01T00:00:00Z"),
    # ── inválidas ──
    "missing signal": rm("signal"), "missing result": rm("result"),
    "missing observed_at": rm("observed_at"), "missing reason": rm("reason"),
    "extra field": ok_obs(extra=1), "extra frames": ok_obs(frames=30),
    "signal unknown": ok_obs(signal="ingest.fps"), "signal case": ok_obs(signal="INGEST.VIDEO"),
    "signal None": ok_obs(signal=None), "signal int": ok_obs(signal=1), "signal list": ok_obs(signal=["ingest.video"]),
    "result lower": ok_obs(result="pass"), "result None": ok_obs(result=None), "result int": ok_obs(result=1),
    "result OK": ok_obs(result="OK"),
    "observed_at naive": ok_obs(observed_at="2026-10-12T12:00:00"),
    "observed_at date only": ok_obs(observed_at="2026-10-12"),
    "observed_at garbage": ok_obs(observed_at="basura"),
    "observed_at int": ok_obs(observed_at=1760270400), "observed_at None": ok_obs(observed_at=None),
    "observed_at month 13": ok_obs(observed_at="2026-13-01T00:00:00Z"),
    "observed_at space sep": ok_obs(observed_at="2026-10-12 12:00:00Z"),
    "observed_at empty": ok_obs(observed_at=""),
    "observed_at future +61": ok_obs(observed_at=S.iso(NOW + timedelta(seconds=61))),
    "observed_at future +1h": ok_obs(observed_at=S.iso(NOW + timedelta(hours=1))),
    "reason empty": ok_obs(reason=""), "reason 301": ok_obs(reason="x" * 301),
    "reason None": ok_obs(reason=None), "reason int": ok_obs(reason=5),
    "metrics None": ok_obs(metrics=None), "metrics list": ok_obs(metrics=[]), "metrics str": ok_obs(metrics="x"),
    "bytes negative": ok_obs(metrics={"bytes": -1}), "bytes bool": ok_obs(metrics={"bytes": True}),
    "bytes float": ok_obs(metrics={"bytes": 1.5}), "bytes str": ok_obs(metrics={"bytes": "5"}),
    "bytes None": ok_obs(metrics={"bytes": None}),
    "objects negative": ok_obs(metrics={"objects": -1}), "objects bool": ok_obs(metrics={"objects": False}),
    "window 0": ok_obs(metrics={"window_seconds": 0}), "window 3601": ok_obs(metrics={"window_seconds": 3601}),
    "window bool": ok_obs(metrics={"window_seconds": True}),
    "http 99": ok_obs(metrics={"http_status": 99}), "http 600": ok_obs(metrics={"http_status": 600}),
    "http bool": ok_obs(metrics={"http_status": True}),
    "metrics extra": ok_obs(metrics={"fps": 30}), "metrics codec": ok_obs(metrics={"bytes": 1, "codec": "h264"}),
}


@pytest.mark.parametrize("label", list(CASES))
def test_validation_matrix_agrees_with_real_schema(label):
    obs = copy.deepcopy(CASES[label])
    want = expected_accept(obs)
    got, msg = I._validate_observation(obs, NOW)
    assert got is want, f"{label}: schema/oráculo={want}, ingest={got} ({msg})"
    if not got:
        assert msg  # siempre explica por qué


def test_matrix_has_both_accepts_and_rejects_so_it_can_fail():
    wants = [expected_accept(copy.deepcopy(c)) for c in CASES.values()]
    assert sum(wants) >= 20 and wants.count(False) >= 35


@pytest.mark.parametrize("raw", [[], "x", 1, 1.5, None, True, [ok_obs()]])
def test_non_object_json_values_are_rejected_not_crash(raw):
    ok, msg = I._validate_observation(raw, NOW)
    assert ok is False and msg


# ── CLI ───────────────────────────────────────────────────────────────────────

def run_main(monkeypatch, lines, redis, env=None):
    monkeypatch.setattr(I, "_redis", lambda: redis)
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(lines) + "\n"))
    monkeypatch.setattr(I, "_now", lambda: NOW, raising=False)
    for k, v in (env or {}).items():
        monkeypatch.setenv(k, v)
    return I.main()


def line(**over):
    return json.dumps(ok_obs(**over))


def test_exit_codes_are_documented_constants():
    assert (I.EXIT_OK, I.EXIT_INVALID_INPUT, I.EXIT_REDIS_UNAVAILABLE) == (0, 1, 2)
    assert "exit" in I.__doc__.lower() and "2" in I.__doc__


def test_all_valid_stored_exit_0(monkeypatch):
    r = FakeRedis()
    lines = [line(signal=s, result="PASS") for s in S.ALL_SIGNALS]
    assert run_main(monkeypatch, lines, r) == 0
    assert set(r.kv) == {f"pipeline:signal:{s}:latest" for s in S.ALL_SIGNALS}  # nada más en claves simples
    assert json.loads(r.kv["pipeline:signal:ingest.video:latest"]) == ok_obs()


def test_invalid_line_does_not_prevent_valid_ones_and_exit_nonzero(monkeypatch, capsys):
    r = FakeRedis()
    lines = [line(signal="ingest.video"), "{no json", line(signal="ingest.audio", reason=""),
             "", line(signal="ingest.data", result="FAIL"), line(extra=1), "[]", line(signal="relay.public")]
    assert run_main(monkeypatch, lines, r) == I.EXIT_INVALID_INPUT == 1
    assert set(r.kv) == {f"pipeline:signal:{s}:latest" for s in ("ingest.video", "ingest.data", "relay.public")}
    err = capsys.readouterr().err
    for n in (2, 3, 6, 7):  # números de línea (1-based) de las inválidas: 2, 3, 6, 7 (la vacía cuenta)
        assert f"Line {n}" in err
    assert json.loads(r.kv["pipeline:signal:ingest.data:latest"])["result"] == "FAIL"


def test_future_observation_rejected_at_ingestion_f(monkeypatch):
    r = FakeRedis()
    assert run_main(monkeypatch, [line(observed_at=S.iso(NOW + timedelta(seconds=61)))], r) == 1
    assert not r.kv


def test_float_integral_metrics_are_normalised_to_int(monkeypatch):
    r = FakeRedis()
    assert run_main(monkeypatch, [line(metrics={"bytes": 5.0, "objects": 2})], r) == 0
    stored = json.loads(r.kv["pipeline:signal:ingest.video:latest"])
    assert stored["metrics"] == {"bytes": 5, "objects": 2} and isinstance(stored["metrics"]["bytes"], int)


def test_redis_missing_is_exit_2_even_with_only_valid_lines_and_no_escape_hatch(monkeypatch):
    for env in (None, {"REDIS_REQUIRED": "false"}):
        assert run_main(monkeypatch, [line()], None, env) == I.EXIT_REDIS_UNAVAILABLE == 2


@pytest.mark.parametrize("k", [0, 1])  # cada observación = 1 EXEC: cae en la 1ª o en la 2ª
def test_redis_dying_mid_stream_is_exit_2_not_0_or_1(monkeypatch, k):
    r = FakeRedis()
    r.fail_after = k
    lines = [line(signal="ingest.video"), line(signal="ingest.audio"), "{no json"]
    assert run_main(monkeypatch, lines, r) == 2


def test_ingest_then_status_end_to_end(monkeypatch):
    r = FakeRedis()
    lines = [line(signal=s, result="FAIL" if s == "ingest.data" else "PASS") for s in S.ALL_SIGNALS]
    assert run_main(monkeypatch, lines, r) == 0
    snap = A.get_snapshot(r, NOW)
    assert S.schema_errors(S.SNAPSHOT_ID, snap) == []
    assert snap["phases"][0]["transport"]["status"] == "DEGRADED"
    assert snap["phases"][1]["transport"]["status"] == "OK"


API = S.API_DIR / "pipeline_ingest.py"


def _cli(stdin: str, env_extra: dict):
    env = {k: v for k, v in os.environ.items() if k != "REDIS_URL"}
    env.update(env_extra)
    return subprocess.run([sys.executable, str(API)], input=stdin, capture_output=True, text=True,
                          env=env, timeout=60, cwd=str(S.REPO))


def test_real_process_without_redis_url_exits_2():
    p = _cli(line() + "\n", {})
    assert p.returncode == 2, p.stderr


def test_real_process_with_unreachable_redis_exits_2():
    p = _cli(line() + "\n", {"REDIS_URL": "redis://127.0.0.1:1/0"})  # puerto 1: nada escucha
    assert p.returncode == 2, p.stderr


def test_ingest_module_has_no_docker_or_subprocess():
    import ast
    tree = ast.parse(API.read_text())
    names = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
    names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert not names & {"subprocess", "docker"}
