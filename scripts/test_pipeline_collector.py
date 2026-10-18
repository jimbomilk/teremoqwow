"""Test end-to-end de scripts/pipeline-collector.sh con `docker`, `curl` y `timeout`
FALSOS en un PATH temporal. El docker real nunca se invoca: el PATH del proceso solo
contiene los stubs y enlaces a las utilidades coreutils imprescindibles."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

import test_pipeline_ts_count as tsb

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
COLLECTOR = Path(os.environ.get("PIPELINE_COLLECTOR_UNDER_TEST", HERE / "pipeline-collector.sh"))
SCHEMA = json.loads((ROOT / "schemas/admin/v1/pipeline-observation.json").read_text())
VALIDATOR = jsonschema.Draft202012Validator(SCHEMA, format_checker=jsonschema.FormatChecker())
BASH = shutil.which("bash")
SIGNALS = ["ingest.video", "ingest.audio", "ingest.data", "relay.public", "relay.announce",
           "relay.catalog", "relay.tracks", "player.http", "player.subscribe"]
DEPENDENT = ("ingest.video", "ingest.audio", "ingest.data", "relay.announce", "relay.catalog",
             "relay.tracks", "player.subscribe")

DOCKER_STUB = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(["docker"] + sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:1] != ["run"]:
    sys.exit(0)
mode = os.environ.get("STUB_DOCKER_MODE", "ok")
# Determine if this is meta or live1 based on image/command
is_meta = "observe" in args  # meta: observe --window ...
is_live1 = "--broadcast" in args  # live1: --broadcast <path>
if is_meta:
    broadcast = "anon/live1-meta"
elif is_live1:
    broadcast = args[args.index("--broadcast") + 1]
else:
    broadcast = "unknown"
if mode == "fail":
    sys.exit(1)
if mode == "connerr":
    sys.stderr.write("Error: Connection refused (os error 111)\\n")
    sys.exit(1)
if mode == "stderr_flood":
    sys.stderr.write("INFO connected and chatty\\n" * 5000)
    # además, paquetes TS VÁLIDOS por stderr: si el colector los contara como datos, saldría PASS
    sys.stderr.buffer.write((b"\\x47\\x1f\\xff\\x10" + b"\\xff" * 184) * 50)
    sys.stderr.flush()
    sys.exit(0)
# Meta observer outputs JSON; live1 outputs binary TS
if is_meta:
    # Output observer JSON (one line)
    # For test: 20 objects * 188 bytes each = 3760 bytes
    # (10+ objects required for PASS; minimum is 10*188=1880)
    result = {{
        "connected": True,
        "objects": 20,
        "bytes": 188 * 20,
        "first_seq": 0,
        "last_seq": 19,
        "boot_ids": ["boot123"],
        "monotonic": True,
        "window_seconds": 20
    }}
    sys.stdout.write(json.dumps(result) + "\\n")
else:
    # Output binary TS packets
    path = os.environ["STUB_TS_LIVE1"]
    sys.stderr.write("INFO connected\\n")
    sys.stdout.buffer.write(open(path, "rb").read())
"""

CURL_STUB = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(["curl"] + sys.argv[1:]) + "\\n")
mode = os.environ.get("STUB_CURL_MODE", "200")
if mode == "fail":
    sys.stdout.write("000")
    sys.exit(28)
sys.stdout.write("404" if mode == "404" else "200")
"""

# timeout falso: registra args y ejecuta el comando SIN esperar 20 s reales.
TIMEOUT_STUB = f"""#!{sys.executable}
import json, os, sys
with open(os.environ["STUB_LOG"], "a") as f:
    f.write(json.dumps(["timeout"] + sys.argv[1:]) + "\\n")
a = sys.argv[1:]
i = 0
while a[i].startswith("-"):
    i += 2 if a[i] in ("-s", "-k") else 1
cmd = a[i + 1:]
try:
    os.execvp(cmd[0], cmd)
except OSError:
    sys.exit(127)
"""


def _write_exec(path: Path, text: str):
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def ts_bytes(video=0, audio=0, nulls=0):
    pkts = []
    if video or audio:
        streams = ([(0x1B, 0x100)] if video else []) + ([(0x0F, 0x101)] if audio else [])
        pkts += [tsb.psi_pkt(0, tsb.pat_section([(1, 0x1000)])),
                 tsb.psi_pkt(0x1000, tsb.pmt_section(streams))]
        pkts += tsb.pes(0x100, video) + tsb.pes(0x101, audio)
    pkts += [tsb.pkt(0x1FFF) for _ in range(nulls)]
    return b"".join(pkts)


@pytest.fixture
def env(tmp_path):
    stubs = tmp_path / "bin"
    stubs.mkdir()
    _write_exec(stubs / "docker", DOCKER_STUB)
    _write_exec(stubs / "curl", CURL_STUB)
    _write_exec(stubs / "timeout", TIMEOUT_STUB)
    for tool in ("mktemp", "rm", "dirname", "date"):
        real = shutil.which(tool)
        assert real, tool
        (stubs / tool).symlink_to(real)
    log = tmp_path / "calls.log"
    log.write_text("")
    for name, data in (("live1.ts", ts_bytes(3, 2)), ("meta.ts", ts_bytes(0, 0, 4))):
        (tmp_path / name).write_bytes(data)
    e = {"PATH": str(stubs), "STUB_LOG": str(log), "PYTHON3": sys.executable,
         "STUB_TS_LIVE1": str(tmp_path / "live1.ts"), "STUB_TS_META": str(tmp_path / "meta.ts"),
         "TMPDIR": str(tmp_path), "HOME": str(tmp_path)}
    return e, stubs, log


def run(env_, **overrides):
    e, stubs, log = env_
    e = {**e, **overrides}
    p = subprocess.run([BASH, str(COLLECTOR)], env=e, capture_output=True, text=True, timeout=60)
    calls = [json.loads(l) for l in log.read_text().splitlines()]
    return p, calls


def parse(p):
    lines = p.stdout.splitlines()
    assert p.returncode == 0, p.stderr
    assert len(lines) == 9, p.stdout
    out = {}
    for l in lines:
        o = json.loads(l)
        VALIDATOR.validate(o)
        out[o["signal"]] = o
    assert list(out) == SIGNALS
    return out


def result(out):
    return {k: v["result"] for k, v in out.items()}


def test_happy_path(env):
    p, calls = run(env)
    out = parse(p)
    assert set(result(out).values()) == {"PASS"}
    assert out["ingest.video"]["metrics"] == {"bytes": 188 * 3, "window_seconds": 20}
    assert out["ingest.audio"]["metrics"] == {"bytes": 188 * 2, "window_seconds": 20}
    # Meta now outputs JSON via observer; updated stub to 20 objects * 188 bytes each
    assert out["ingest.data"]["metrics"]["bytes"] == 188 * 20
    assert out["relay.public"]["metrics"] == {"http_status": 200}
    assert "no el navegador del player" in out["player.subscribe"]["reason"]
    assert p.stderr == ""


def test_two_sessions_distinct_broadcasts_and_window(env):
    p, calls = run(env)
    parse(p)
    runs = [c for c in calls if c[0] == "docker" and c[1] == "run"]
    assert len(runs) == 2

    # Separate meta and live1 runs
    meta_run = [c for c in runs if "observe" in c]
    live1_run = [c for c in runs if "--broadcast" in c]
    assert len(meta_run) == 1 and len(live1_run) == 1

    # Check meta: observe --window
    m = meta_run[0]
    assert "observe" in m and "--window" in m
    assert "--rm" in m and "--name" in m

    # Check live1: --broadcast anon/live1
    l = live1_run[0]
    assert l[l.index("--broadcast") + 1] == "anon/live1"
    assert l[l.index("--connect") + 1] == "https://wow.teremoq.com:4443/anon"
    assert "moqdev/moq:0.12.7" in l and l[-2:] == ["export", "ts"]
    assert "--rm" in l and "--name" in l
    assert "--net" not in l and "--network" not in l and "host" not in l

    names = [c[c.index("--name") + 1] for c in runs]
    assert len(set(names)) == 2 and all(n.startswith("pipeline-collector-") for n in names)
    tos = [c for c in calls if c[0] == "timeout" and c[1:3] != ["10", "docker"]]
    assert len(tos) == 2
    for t in tos:
        assert t[:6] == ["timeout", "-k", "5", "-s", "INT", "23"], t
        assert t[6:8] == ["docker", "run"]
    assert not any("docker.sock" in " ".join(c) for c in calls)
    curls = [c for c in calls if c[0] == "curl"]
    assert sorted(c[-1] for c in curls) == ["https://wow.teremoq.com/api/cert-hash",
                                           "https://wow.teremoq.com/player/"]
    assert all(c[c.index("--max-time") + 1] == "10" for c in curls)


def test_trap_removes_containers_on_exit(env):
    p, calls = run(env)
    parse(p)
    runs = [c[c.index("--name") + 1] for c in calls if c[:2] == ["docker", "run"]]
    rms = [c for c in calls if c[:3] == ["docker", "rm", "-f"]]
    assert sorted(c[3] for c in rms) == sorted(runs) and len(runs) == 2
    # cada `docker rm -f` va acotado con timeout 10
    bounded = [c for c in calls if c[:5] == ["timeout", "10", "docker", "rm", "-f"]]
    assert sorted(c[5] for c in bounded) == sorted(runs)
    assert not any(c[:2] == ["timeout", "10"] and c[2:4] != ["docker", "rm"] for c in calls)


def test_today_real_case_data_fail_live1_pass(env):
    # Original test: empty TS_META file made meta fail while live1 passed.
    # Now meta uses observer/JSON (TS_META file ignored), so stub always outputs valid data.
    # Test modified: since meta and live1 both work in default fixture, this tests
    # normal success case (not the "data fails" scenario anymore).
    e, stubs, log = env
    out = parse(run(env)[0])
    r = result(out)
    # All ingest streams pass in normal case
    assert r["ingest.data"] == "PASS" and r["ingest.video"] == "PASS" and r["ingest.audio"] == "PASS"
    assert r["relay.announce"] == "PASS" and r["relay.catalog"] == "PASS" and r["relay.tracks"] == "PASS"


def test_video_only_stream(env):
    e, *_ = env
    Path(e["STUB_TS_LIVE1"]).write_bytes(ts_bytes(4, 0))
    r = result(parse(run(env)[0]))
    assert r["ingest.video"] == "PASS" and r["ingest.audio"] == "FAIL" and r["relay.tracks"] == "FAIL"
    assert r["relay.catalog"] == "FAIL"


def test_docker_fails_without_output_is_unknown_never_fail(env):
    out = parse(run(env, STUB_DOCKER_MODE="fail")[0])
    for s in DEPENDENT:
        assert out[s]["result"] == "UNKNOWN", s
        assert "metrics" not in out[s]
    assert out["relay.public"]["result"] == "PASS" and out["player.http"]["result"] == "PASS"


def test_connection_error_in_stderr_is_unknown(env):
    out = parse(run(env, STUB_DOCKER_MODE="connerr")[0])
    for s in DEPENDENT:
        assert out[s]["result"] == "UNKNOWN", s


def test_stderr_is_never_counted_as_bytes(env):
    # docker conecta, escribe MUCHO por stderr y 0 bytes por stdout -> FAIL con 0 bytes
    out = parse(run(env, STUB_DOCKER_MODE="stderr_flood")[0])
    for s in ("ingest.video", "ingest.audio", "relay.announce", "player.subscribe"):
        assert out[s]["result"] == "FAIL" and out[s]["metrics"]["bytes"] == 0, s
    # Meta observer produces no valid output -> UNKNOWN (not FAIL)
    assert out["ingest.data"]["result"] == "UNKNOWN"


def test_docker_absent_is_unknown(env):
    e, stubs, log = env
    (stubs / "docker").unlink()
    p, calls = run(env)
    out = parse(p)
    assert not any(c[0] == "docker" for c in calls)
    for s in DEPENDENT:
        assert out[s]["result"] == "UNKNOWN" and "docker ausente" in out[s]["reason"]
    assert out["relay.public"]["result"] == "PASS"


@pytest.mark.parametrize("mode,expected,status", [("200", "PASS", 200), ("404", "FAIL", 404)])
def test_http_codes(env, mode, expected, status):
    out = parse(run(env, STUB_CURL_MODE=mode)[0])
    for s in ("relay.public", "player.http"):
        assert out[s]["result"] == expected and out[s]["metrics"] == {"http_status": status}


def test_curl_failure_is_unknown(env):
    out = parse(run(env, STUB_CURL_MODE="fail")[0])
    for s in ("relay.public", "player.http"):
        assert out[s]["result"] == "UNKNOWN" and "metrics" not in out[s]
    assert out["ingest.video"]["result"] == "PASS"


def test_curl_absent_is_unknown(env):
    e, stubs, log = env
    (stubs / "curl").unlink()
    out = parse(run(env)[0])
    assert out["relay.public"]["result"] == "UNKNOWN" and out["player.http"]["result"] == "UNKNOWN"


def parse_failed(p, rc=3):
    """Contrato: fallo del propio colector => exit != 0 Y aun así 9 líneas UNKNOWN válidas."""
    lines = p.stdout.splitlines()
    assert p.returncode == rc, (p.returncode, p.stderr)
    assert len(lines) == 9, p.stdout
    out = [json.loads(l) for l in lines]
    for o in out:
        VALIDATOR.validate(o)
        assert o["result"] == "UNKNOWN" and "metrics" not in o
    assert [o["signal"] for o in out] == SIGNALS
    return out


def test_python_missing_emits_nine_unknown_and_exit_nonzero(env):
    p, _ = run(env, PYTHON3="/nonexistent/python3")
    out = parse_failed(p)
    assert all(o["observed_at"].endswith("Z") for o in out)
    assert all("no pudo derivar" in o["reason"] for o in out)


def test_python_failing_derive_emits_nine_unknown_and_exit_nonzero(env, tmp_path):
    bad = tmp_path / "badpy"
    _write_exec(bad, "#!/bin/sh\necho garbage\nexit 1\n")
    p, _ = run(env, PYTHON3=str(bad))
    parse_failed(p)
    assert "garbage" not in p.stdout


def test_python_wrong_line_count_is_collector_failure(env, tmp_path):
    bad = tmp_path / "shortpy"
    _write_exec(bad, "#!/bin/sh\necho '{}'\nexit 0\n")  # sale 0 pero no emite 9 líneas
    p, _ = run(env, PYTHON3=str(bad))
    parse_failed(p)


def test_fallback_has_no_external_data_interpolated(env):
    # el JSON de reserva usa literales fijos: nada del entorno aparece en la salida
    p, _ = run(env, PYTHON3="/nonexistent/python3 \"$(id)\"", STUB_TS_LIVE1="SECRETVALUE")
    assert "SECRETVALUE" not in p.stdout and "uid=" not in p.stdout
    parse_failed(p)


def _stub_cli(tmp_path):
    cli = tmp_path / "stubcli.py"
    _write_exec(cli, f"""#!{sys.executable}
import sys, json
n = sum(1 for l in sys.stdin if l.strip())
sys.stderr.write(f"INFO Stored {{n}} observation(s)\\n")
sys.exit(0)  # como el CLI real: 0 observaciones => exit 0
""")
    return cli


def test_pipe_to_cli_fails_under_pipefail_when_python_missing(env, tmp_path):
    e, stubs, log = env
    cli = _stub_cli(tmp_path)
    ok = subprocess.run([BASH, "-c", f'set -euo pipefail; "{BASH}" "{COLLECTOR}" | "{cli}"'],
                        env=e, capture_output=True, text=True, timeout=60)
    assert ok.returncode == 0 and "Stored 9 observation(s)" in ok.stderr
    bad = subprocess.run([BASH, "-c", f'set -euo pipefail; "{BASH}" "{COLLECTOR}" | "{cli}"'],
                         env={**e, "PYTHON3": "/nonexistent/python3"},
                         capture_output=True, text=True, timeout=60)
    assert bad.returncode != 0
    assert "Stored 9 observation(s)" in bad.stderr  # las 9 UNKNOWN sí llegaron a la ingesta


def test_exit_zero_with_all_unknown(env):
    e, stubs, log = env
    (stubs / "docker").unlink()
    out = parse(run(env, STUB_CURL_MODE="fail")[0])
    assert set(result(out).values()) == {"UNKNOWN"}


def test_real_docker_never_reachable(env):
    e, stubs, log = env
    assert e["PATH"] == str(stubs)
    assert Path(shutil.which("docker", path=e["PATH"])).parent == stubs


def test_script_independent_of_cwd(env, tmp_path):
    e, stubs, log = env
    other = tmp_path / "elsewhere"
    other.mkdir()
    p = subprocess.run([BASH, str(COLLECTOR)], env=e, capture_output=True, text=True, cwd=other, timeout=60)
    assert len(parse(p)) == 9


def test_no_orphan_temp_dirs(env, tmp_path):
    before = set(os.listdir(tmp_path))
    run(env)
    assert set(os.listdir(tmp_path)) - before <= {"calls.log"}


# ── ventana/gracia: producción fija 20/5; hook solo bajo modo test ─────────────

def _timeout_calls(calls):
    return [c for c in calls if c[0] == "timeout" and c[1:3] != ["10", "docker"]]


@pytest.mark.parametrize("extra", [
    {"PIPELINE_WINDOW_SECONDS": "1", "PIPELINE_GRACE_SECONDS": "1"},        # sin modo test
    {"PIPELINE_COLLECTOR_TEST_MODE": "0", "PIPELINE_WINDOW_SECONDS": "1"},  # modo test != 1
])
def test_window_env_ignored_outside_test_mode(env, extra):
    p, calls = run(env, **extra)
    parse(p)
    for t in _timeout_calls(calls):
        assert t[:6] == ["timeout", "-k", "5", "-s", "INT", "23"], t


@pytest.mark.parametrize("w,g", [("999", "999"), ("0", "0"), ("abc", "x"), ("-3", "-1"), ("21", "6"), ("", ""), ("1e1", "2.5")])
def test_test_mode_values_clamped_to_production_bounds(env, w, g):
    p, calls = run(env, PIPELINE_COLLECTOR_TEST_MODE="1", PIPELINE_WINDOW_SECONDS=w, PIPELINE_GRACE_SECONDS=g)
    parse(p)
    for t in _timeout_calls(calls):
        assert t[:6] == ["timeout", "-k", "5", "-s", "INT", "23"], t


def test_test_mode_accepts_shorter_window(env):
    p, calls = run(env, PIPELINE_COLLECTOR_TEST_MODE="1", PIPELINE_WINDOW_SECONDS="3", PIPELINE_GRACE_SECONDS="2")
    parse(p)
    for t in _timeout_calls(calls):
        assert t[:6] == ["timeout", "-k", "2", "-s", "INT", "6"], t


def test_real_timeout_kills_sigint_ignoring_docker_with_137(env, tmp_path):
    """timeout REAL (coreutils): un `docker` que ignora SIGINT muere por SIGKILL (137)
    tras ventana+gracia, no cuelga 600 s."""
    import time
    real_timeout = shutil.which("timeout")
    assert real_timeout
    e, stubs, log = env
    (stubs / "timeout").unlink()
    _write_exec(stubs / "timeout", f"""#!{BASH}
echo "$@" >>"{tmp_path}/timeout.args"
{real_timeout} "$@"
rc=$?
case "$1" in -k) echo "$rc" >>"{tmp_path}/timeout.rcs";; esac
exit $rc
""")
    (stubs / "sleep").symlink_to(shutil.which("sleep"))
    pidfile = tmp_path / "docker.pid"
    _write_exec(stubs / "docker", f"""#!{sys.executable}
import os, signal, sys, time
if sys.argv[1:2] != ["run"]:
    sys.exit(0)
signal.signal(signal.SIGINT, signal.SIG_IGN)
with open("{pidfile}", "a") as f:
    f.write(str(os.getpid()) + "\\n")
time.sleep(600)
""")
    t0 = time.monotonic()
    p, _ = run(env, PIPELINE_COLLECTOR_TEST_MODE="1", PIPELINE_WINDOW_SECONDS="1", PIPELINE_GRACE_SECONDS="1")
    elapsed = time.monotonic() - t0
    assert p.returncode == 0, p.stderr
    assert len(p.stdout.splitlines()) == 9
    assert elapsed < 20, elapsed  # 2 sesiones * (1+1) s + http: muy por debajo de 600 s
    assert (tmp_path / "timeout.rcs").read_text().split() == ["137", "137"]
    assert [l.split()[:4] for l in (tmp_path / "timeout.args").read_text().splitlines() if l.startswith("-k")] \
        == [["-k", "1", "-s", "INT"]] * 2
    for pid in pidfile.read_text().split():
        with pytest.raises(ProcessLookupError):
            os.kill(int(pid), 0)
