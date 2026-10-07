import os
import re
import json
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_NAMES = (
    "integration-test.sh",
    "verify-sync-track.sh",
    "verify-lipsync.sh",
    "verify-pts-sync.sh",
    "measure-e2e.sh",
    "qos-diagnostics.sh",
)


@pytest.fixture
def isolated_ci_path(tmp_path):
    scripts = tmp_path / "qos" / "scripts"
    scripts.mkdir(parents=True)
    for name in SCRIPT_NAMES:
        source = REPO_ROOT / "qos" / "scripts" / name
        # Redirect legacy fixed /tmp artifacts into this test's private directory.
        content = source.read_text().replace("/tmp/", f"{tmp_path}/")
        (scripts / name).write_text(content)

    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    docker_log = tmp_path / "docker-calls.log"
    (shim_dir / "docker").write_text(
        """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$QOS_DOCKER_LOG"
args="$*"
case "$args" in
  *"network ls"*) printf 'NETWORK ID NAME\\n123 teremoqwow-e2e\\n' ;;
  *"network inspect"*) exit 0 ;;
  *"inspect moq-relay"*) exit 0 ;;
  *"ps --format"*) printf 'moq-relay\n' ;;
  *"ps -q"*) ;;
  *"export ts"*)
    exporter_rc="$QOS_EXPORTER_RC"
    exporter_data="$QOS_EXPORTER_DATA"
    if [[ "$LIPSYNC_READINESS_ONLY" == "1" ]]; then
      exporter_rc="${QOS_READINESS_EXPORTER_RC:-$exporter_rc}"
      exporter_data="${QOS_READINESS_EXPORTER_DATA:-$exporter_data}"
    fi
    if [[ "$exporter_rc" != "0" ]]; then
      if [[ -n "${QOS_EXPORTER_STDERR:-}" ]]; then
        [[ "$exporter_data" == "1" ]] && printf 'fixture stream bytes\\n'
        printf '%b\\n' "$QOS_EXPORTER_STDERR" >&2
      else
        printf 'export failed token=fixture_export_value\\n' >&2
      fi
      exit "$exporter_rc"
    fi
    if [[ "$exporter_data" == "1" ]]; then
      printf 'fixture stream bytes\\n'
    fi
    exit 0
    ;;
  *"fetch catalog.json"*)
    printf '{"clock":{"wall":%s},"video":{},"audio":{}}\\n' "${QOS_CATALOG_WALL:-1000000}"
    ;;
  *"--help"*) exit 0 ;;
  *) exit 0 ;;
esac
"""
    )
    (shim_dir / "ffprobe").write_text(
        """#!/usr/bin/env bash
stream_data="$(cat)"
ffprobe_rc="${QOS_FFPROBE_RC:-0}"
if [[ "$LIPSYNC_READINESS_ONLY" == "1" ]]; then
  ffprobe_rc="${QOS_READINESS_FFPROBE_RC:-$ffprobe_rc}"
fi
if [[ -z "$stream_data" ]]; then
  if [[ "$ffprobe_rc" != "0" ]]; then
    : > "$QOS_FFPROBE_INVOKED"
    printf 'decoder failed token=fixture_decoder_value' >&2
  fi
  printf '{"frames":[]}\\n'
  exit "$ffprobe_rc"
fi
if [[ "$LIPSYNC_READINESS_ONLY" == "1" && "$QOS_READINESS_FORCE_VALID" == "1" ]]; then
  printf '{"frames":[{"media_type":"video","pts_time":"0"},{"media_type":"audio","pts_time":"0"}]}\\n'
elif [[ "$QOS_MEASURE_FRAMES" == "malformed" ]]; then
  printf 'media_type=video|pts_time=not-a-number\\n'
elif [[ "$QOS_MEASURE_FRAMES" == "large" ]]; then
  printf 'media_type=video|pts_time=60\\n'
elif [[ "$QOS_MEASURE_FRAMES" == "1" ]]; then
  printf 'media_type=video|pts_time=0\\n'
elif [[ "$QOS_FFPROBE_FRAME_MODE" == "video" ]]; then
  printf '{"frames":[{"media_type":"video","pts_time":"1"}]}\\n'
elif [[ "$QOS_FFPROBE_FRAME_MODE" == "audio" ]]; then
  printf '{"frames":[{"media_type":"audio","pts_time":"1"}]}\\n'
elif [[ "$QOS_FFPROBE_FRAME_MODE" == "zero" ]]; then
  printf '{"frames":[{"media_type":"video","pts_time":"0"},{"media_type":"audio","pts_time":"0"}]}\\n'
elif [[ "$QOS_FFPROBE_FRAME_MODE" == "offset" ]]; then
  printf '{"frames":[{"media_type":"video","pts_time":"0"},{"media_type":"audio","pts_time":"0.05"}]}\\n'
elif [[ "$QOS_FFPROBE_FRAME_MODE" == "threshold" ]]; then
  printf '{"frames":[{"media_type":"video","pts_time":"0"},{"media_type":"audio","pts_time":"0.044"}]}\\n'
elif [[ "$QOS_FFPROBE_FRAME_MODE" == "threshold_exact" ]]; then
  printf '{"frames":[{"media_type":"video","pts_time":"0"},{"media_type":"audio","pts_time":"0.045"}]}\\n'
elif [[ "$QOS_FFPROBE_VALID_FRAMES" == "1" ]]; then
  printf '{"frames":[{"media_type":"video","pts_time":"0"},{"media_type":"audio","pts_time":"0"}]}\\n'
elif [[ "$LIPSYNC_READINESS_ONLY" == "1" && "$QOS_READINESS_FORCE_VALID" == "1" ]]; then
  printf '{"frames":[{"media_type":"video","pts_time":"0"},{"media_type":"audio","pts_time":"0"}]}\\n'
else
  printf '{"frames":[]}\\n'
fi
if [[ "$ffprobe_rc" != "0" ]]; then
  : > "$QOS_FFPROBE_INVOKED"
  printf 'decoder failed token=fixture_decoder_value' >&2
  exit "$ffprobe_rc"
fi
exit 0
"""
    )
    (shim_dir / "sleep").write_text("#!/usr/bin/env bash\nexit 0\n")
    (shim_dir / "timeout").write_text(
        """#!/usr/bin/env bash
deadline="$1"
shift
start_ms="${QOS_READINESS_START_MS:-0}"
now_ms="${QOS_READINESS_NOW_MS:-$((start_ms + ${QOS_READINESS_ELAPSED_MS:-0}))}"
# Only the readiness gate (timeout <D> bash .../verify-lipsync.sh) is killed
# by elapsed time; ffprobe's own timeout is told apart by its command, never
# by the numeric deadline (they can coincide).
if [[ "$1" == "bash" && "$2" == */verify-lipsync.sh && $((now_ms - start_ms)) -ge $((deadline * 1000)) ]]; then
  exit 124
fi
exec "$@"
"""
    )
    for shim in shim_dir.iterdir():
        shim.chmod(0o755)

    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{shim_dir}:{env['PATH']}",
            "QOS_DOCKER_LOG": str(docker_log),
            "QOS_EXPORTER_RC": "37",
            "QOS_EXPORTER_DATA": "1",
            "QOS_READINESS_EXPORTER_RC": "0",
            "QOS_READINESS_EXPORTER_DATA": "1",
            "QOS_READINESS_FFPROBE_RC": "0",
            "QOS_READINESS_FORCE_VALID": "1",
            "QOS_FFPROBE_RC": "29",
            "QOS_FFPROBE_INVOKED": str(tmp_path / "ffprobe-invoked"),
            "SKIP_NETEM": "1",
            "SKIP_REMOTE_CHECK": "1",
            "SKIP_REMOTE_LATENCY": "1",
            "SKIP_CERT_CHECK": "1",
            "WINDOW_SEC": "1",
            "TMPDIR": str(tmp_path),
            "LIPSYNC_REPORT_FILE": str(tmp_path / "lipsync-report.json"),
        }
    )
    return scripts, docker_log, env, tmp_path


@pytest.fixture
def ci_result(isolated_ci_path):
    scripts, docker_log, env, tmp_path = isolated_ci_path
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )
    return result, docker_log.read_text(), tmp_path


def test_ci_path_reports_sanitized_exporter_and_decoder_failures(ci_result):
    result, _, _ = ci_result
    output = result.stdout

    assert result.returncode != 0
    assert output.count("[QOS-DIAGNOSTIC] stage=exporter exit=37") >= 3
    assert output.count("[QOS-DIAGNOSTIC] stage=ffprobe exit=29") >= 3
    assert "token=[REDACTED]" in output
    assert "decoder failed token=[REDACTED]" in output
    assert "fixture_decoder_value" not in output


def test_ci_path_does_not_turn_tool_errors_into_empty_measurement_pass(ci_result):
    result, _, tmp_path = ci_result
    output = result.stdout
    pts_report = (tmp_path / "pts-sync-report.json").read_text()

    assert "[PTS-SYNC] FAIL" in output
    assert '"events_sampled": 0' in pts_report
    assert '"pass": false' in pts_report
    assert "[INTEGRATION] ✗ FAIL: Latencia glass-to-glass" in output
    assert "RESULT: FAIL" in output
    assert result.returncode != 0


def test_ci_path_uses_only_temporary_docker_shim(ci_result):
    _, docker_calls, _ = ci_result

    assert "moq-relay" in docker_calls
    assert "export ts" in docker_calls


@pytest.mark.parametrize(
    ("diagnostic", "sentinels"),
    [
        ("password: fixture secret phrase\n", ("secret phrase",)),
        ("{'password': 'single-secret'}\n", ("single-secret",)),
        (
            "{'password': 'pwn\\'ed\"x'}\n",
            ("pwn\\'ed\"x",),
        ),
        ("Authorization: " + "Bear" + "er fixture multiword secret\n", ("fixture multiword secret",)),
        ("Bear" + "er standalone-" + "sec" + "ret\n", ("standalone-secret",)),
        ('{"access_token":"json-fixture-access-value","password": "json-fixture-password-value"}\n', ("json-fixture-access-value", "json-fixture-password-value")),
        ('token: \'secret-value\' {"token": \'json-secret\'}\n', ("secret-value", "json-secret")),
        ("export failed at https://fixture-user:fixture-pass@media.example/export?sig=query fixture signature&session=query fixture session&quality=low\n",
         ("query fixture signature", "query fixture session")),
        ("export failed at tcp://fixture-user:fixture-pass@relay.example/export?session=tcp fixture session&track=video\n",
         ("tcp fixture session",)),
        ("https://user:fixture secret phrase@example.test/path\n",
         ("fixture secret phrase",)),
        ("https://user:p" + "@ss@example/x\n", ("p@ss",)),
    ],
)
def test_diagnostic_sanitizer_redacts_header_and_json_secrets(
    tmp_path, diagnostic, sentinels
):
    stderr_file = tmp_path / "diagnostic.txt"
    stderr_file.write_text(diagnostic)
    result = subprocess.run(
        [
            "bash",
            "-c",
            'source "$1"; qos_report_tool_diagnostic exporter 1 "$2"',
            "bash",
            str(REPO_ROOT / "qos" / "scripts" / "qos-diagnostics.sh"),
            str(stderr_file),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )

    assert result.returncode == 0
    assert all(secret not in result.stderr for secret in sentinels)
    assert "[REDACTED]" in result.stderr
    if "media.example" in diagnostic:
        assert "https://[REDACTED]@media.example/export" in result.stderr
        assert "?sig=[REDACTED]&session=[REDACTED]&quality=low" in result.stderr
    if "relay.example" in diagnostic:
        assert "tcp://[REDACTED]@relay.example/export" in result.stderr
        assert "?session=[REDACTED]&track=video" in result.stderr


def test_pts_sync_rejects_empty_successful_export(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = subprocess.run(
        ["bash", str(scripts / "verify-pts-sync.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    report = (tmp_path / "pts-sync-report.json").read_text()

    assert result.returncode != 0
    assert "[PTS-SYNC] FAIL" in result.stdout
    assert '"events_sampled": 0' in report
    assert '"pass": false' in report


def test_pts_sync_does_not_read_stale_global_artifacts(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    # The fixture rewrites the scripts' "/tmp/" to tmp_path, so these are exactly
    # the "global" artifact paths the script could wrongly pick up. Never touch
    # the real /tmp: fixed paths there follow symlinks and can clobber others'
    # files.
    (tmp_path / "video-pts.txt").write_text("10\n")
    (tmp_path / "telemetry-events.json").write_text('{"timestamp":{"unix_ms":10000}}\n')
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_EXPORTER_DATA"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = subprocess.run(
        ["bash", str(scripts / "verify-pts-sync.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    report = json.loads((tmp_path / "pts-sync-report.json").read_text())

    assert result.returncode != 0
    assert report["events_sampled"] == 0
    assert report["pass"] is False


@pytest.mark.parametrize("script_name, report_env", [
    ("verify-lipsync.sh", "LIPSYNC_REPORT_FILE"),
    ("verify-pts-sync.sh", "PTS_REPORT_FILE"),
])
@pytest.mark.parametrize("attack", ["symlink", "hardlink", "parent"])
def test_report_writer_rejects_unsafe_path_without_modifying_target(
    isolated_ci_path, script_name, report_env, attack
):
    scripts, _, env, tmp_path = isolated_ci_path
    target = tmp_path / "symlink-target"
    target.write_text("sentinel")
    if attack == "parent":
        real_parent = tmp_path / "real-parent"
        real_parent.mkdir()
        report = real_parent / "report.json"
        report_parent = tmp_path / "report-parent"
        report_parent.symlink_to(real_parent, target_is_directory=True)
        report = report_parent / "report.json"
    else:
        report = tmp_path / "report.json"
        if attack == "symlink":
            report.symlink_to(target)
        else:
            report.hardlink_to(target)
    env[report_env] = str(report)
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_EXPORTER_DATA"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = subprocess.run(
        ["bash", str(scripts / script_name)],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert target.read_text() == "sentinel"
    if attack == "parent":
        assert not (tmp_path / "real-parent" / "report.json").exists()
    else:
        assert report.is_symlink() if attack == "symlink" else report.stat().st_nlink == 2


def test_overlay_report_writer_rejects_symlink(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    target = tmp_path / "overlay-target"
    target.write_text("sentinel")
    report = tmp_path / "overlay-report.json"
    report.symlink_to(target)
    env["OVERLAY_REPORT_FILE"] = str(report)
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_EXPORTER_DATA"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = subprocess.run(
        ["bash", str(scripts / "verify-pts-sync.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert target.read_text() == "sentinel"
    assert report.is_symlink()


def test_report_writer_reduces_existing_report_permissions(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    report = tmp_path / "existing-report.json"
    report.write_text("{}")
    report.chmod(0o644)
    env["LIPSYNC_REPORT_FILE"] = str(report)
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_EXPORTER_DATA"] = "1"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_FRAME_MODE"] = "zero"
    subprocess.run(
        ["bash", str(scripts / "verify-lipsync.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=10, check=False,
    )

    assert report.stat().st_mode & 0o777 == 0o600


def test_ci_path_fails_on_local_inconclusive_latency(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    (scripts / "measure-e2e.sh").write_text("#!/usr/bin/env bash\nexit 2\n")
    (scripts / "measure-e2e.sh").chmod(0o755)
    for name in ("verify-sync-track.sh", "verify-lipsync.sh", "verify-pts-sync.sh"):
        (scripts / name).write_text("#!/usr/bin/env bash\nexit 0\n")
        (scripts / name).chmod(0o755)
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"

    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )

    assert result.returncode != 0
    assert "Latencia glass-to-glass inconclusive" in result.stdout
    assert "RESULT: FAIL" in result.stdout


def test_ci_path_rejects_negative_capture_latency(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_CATALOG_WALL"] = "999999999999999999"
    env["QOS_MEASURE_FRAMES"] = "1"
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=20, check=False,
    )

    assert result.returncode != 0
    assert "Invalid capture timing" in result.stdout
    assert "RESULT: PASS" not in result.stdout


@pytest.mark.parametrize("measure_mode", ["malformed", "large"])
def test_ci_path_rejects_invalid_capture_timing(isolated_ci_path, measure_mode):
    scripts, _, env, _ = isolated_ci_path
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_CATALOG_WALL"] = "1000000"
    env["QOS_MEASURE_FRAMES"] = measure_mode
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=20, check=False,
    )

    assert result.returncode != 0
    assert "Invalid capture timing" in result.stdout
    assert "RESULT: PASS" not in result.stdout


def test_integration_gates_measurements_on_media_readiness_failure(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    env["MEDIA_READINESS_GATE"] = "1"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_READINESS_FORCE_VALID"] = "0"
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=20, check=False,
    )

    assert result.returncode != 0
    assert "Media readiness DATA_PATH_FAILURE" in result.stdout
    assert "CHECK 1/4: Track de sincronía" not in result.stdout


@pytest.mark.parametrize("window", [5, 15, 30])
@pytest.mark.parametrize("offset_ms", [-1, 0, 1])
def test_media_readiness_deadline_is_window_plus_margin_plus_slack(
    isolated_ci_path, window, offset_ms
):
    """Gate deadline = WINDOW_SEC + ffprobe margin + 10 s: it must outlive the
    inner ffprobe timeout so the ffprobe exit=124 diagnostic is still emitted."""
    scripts, _, env, _ = isolated_ci_path
    deadline_sec = window + MIN_FFPROBE_TIMEOUT_MARGIN_SEC + GATE_SLACK_SEC
    env["WINDOW_SEC"] = str(window)
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_VALID_FRAMES"] = "1"
    env["QOS_READINESS_FORCE_VALID"] = "1"
    env["QOS_READINESS_START_MS"] = "100000"
    env["QOS_READINESS_NOW_MS"] = str(100000 + deadline_sec * 1000 + offset_ms)
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=20, check=False,
    )

    if offset_ms < 0:
        assert "Media readiness READY" in result.stdout
    else:
        assert "Media readiness DATA_PATH_FAILURE" in result.stdout
        assert "Media readiness READY" not in result.stdout
        assert "CHECK 1/4: Track de sincronía" not in result.stdout


@pytest.mark.parametrize(
    ("frame_mode", "expected"),
    [
        ("video", "Media readiness DATA_PATH_FAILURE"),
        ("audio", "Media readiness DATA_PATH_FAILURE"),
        ("", "Media readiness DATA_PATH_FAILURE"),
    ],
)
def test_media_readiness_requires_audio_and_video_frames(
    isolated_ci_path, frame_mode, expected
):
    scripts, _, env, _ = isolated_ci_path
    env["MEDIA_READINESS_GATE"] = "1"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_READINESS_FORCE_VALID"] = "0"
    if frame_mode:
        env["QOS_FFPROBE_FRAME_MODE"] = frame_mode
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )

    assert result.returncode != 0
    assert expected in result.stdout
    assert "CHECK 1/4: Track de sincronía" not in result.stdout


def test_media_readiness_av_frames_before_deadline_allows_measurements(
    isolated_ci_path,
):
    scripts, _, env, _ = isolated_ci_path
    env["MEDIA_READINESS_GATE"] = "1"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_VALID_FRAMES"] = "1"
    env["QOS_READINESS_EXPORTER_DATA"] = "1"
    env["QOS_READINESS_FORCE_VALID"] = "1"
    # 1 ms before the gate deadline: WINDOW_SEC(1) + ffprobe margin + gate slack
    env["QOS_READINESS_ELAPSED_MS"] = str(
        (1 + MIN_FFPROBE_TIMEOUT_MARGIN_SEC + GATE_SLACK_SEC) * 1000 - 1
    )
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )

    assert "Media readiness READY: audio_frames>0 and video_frames>0" in result.stdout
    assert "CHECK 1/4: Track de sincronía" in result.stdout
    assert result.stdout.index("Media readiness READY") < result.stdout.index(
        "CHECK 1/4: Track de sincronía"
    )


def test_media_readiness_is_not_a_lipsync_quality_check(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    env["MEDIA_READINESS_GATE"] = "1"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_EXPORTER_DATA"] = "1"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_FRAME_MODE"] = "offset"
    # 1 ms before the gate deadline: WINDOW_SEC(1) + ffprobe margin + gate slack
    env["QOS_READINESS_ELAPSED_MS"] = str(
        (1 + MIN_FFPROBE_TIMEOUT_MARGIN_SEC + GATE_SLACK_SEC) * 1000 - 1
    )
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )

    assert "Media readiness READY: audio_frames>0 and video_frames>0" in result.stdout
    assert "[INTEGRATION] ✗ FAIL: Lip-sync offset=" in result.stdout


def test_readiness_only_does_not_create_or_modify_lipsync_report(
    isolated_ci_path,
):
    scripts, _, env, tmp_path = isolated_ci_path
    report = tmp_path / "readiness-only-report.json"
    env["LIPSYNC_REPORT_FILE"] = str(report)
    env["LIPSYNC_READINESS_ONLY"] = "1"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_EXPORTER_DATA"] = "1"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_FRAME_MODE"] = "offset"
    result = subprocess.run(
        ["bash", str(scripts / "verify-lipsync.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=10, check=False,
    )

    assert result.returncode == 0
    assert not report.exists()


@pytest.mark.parametrize(
    ("frame_mode", "expected_rc", "expected_pass"),
    [("threshold", 0, True), ("threshold_exact", 1, False)],
)
def test_lipsync_threshold_boundary_and_pass_report(
    isolated_ci_path, frame_mode, expected_rc, expected_pass
):
    scripts, _, env, tmp_path = isolated_ci_path
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_EXPORTER_DATA"] = "1"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_FRAME_MODE"] = frame_mode
    env["THRESHOLD_MS"] = "45"
    result = subprocess.run(
        ["bash", str(scripts / "verify-lipsync.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=10, check=False,
    )
    report = json.loads((tmp_path / "lipsync-report.json").read_text())

    assert result.returncode == expected_rc
    assert report["pass"] is expected_pass


def test_media_readiness_rejects_zero_byte_export(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    env["MEDIA_READINESS_GATE"] = "1"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_EXPORTER_DATA"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_VALID_FRAMES"] = "1"
    env["QOS_READINESS_EXPORTER_DATA"] = "0"
    env["QOS_READINESS_FORCE_VALID"] = "0"
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )

    assert result.returncode != 0
    assert "Media readiness DATA_PATH_FAILURE" in result.stdout
    assert "Media readiness READY" not in result.stdout


def test_ci_path_reports_decoder_only_failure(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "29"
    result = subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )

    assert "[QOS-DIAGNOSTIC] stage=exporter exit=0" in result.stdout
    assert "[QOS-DIAGNOSTIC] stage=ffprobe exit=29" in result.stdout
    assert "Exporter/decoder failed; latency measurement unavailable" in result.stdout
    assert (tmp_path / "ffprobe-invoked").is_file()
    assert "fixture_decoder_value" not in result.stdout
    assert "[INTEGRATION] ✗ FAIL: Latencia glass-to-glass" in result.stdout
    assert result.returncode != 0


@pytest.mark.parametrize("invocation", ["env", "cli"])
def test_measure_rejects_injected_duration_before_execution(tmp_path, invocation):
    marker = tmp_path / "duration-marker"
    payload = f"x[$(touch {marker})0]"
    env = os.environ.copy()
    env["PATH"] = os.environ["PATH"]
    command = ["bash", str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh")]
    if invocation == "env":
        env["DURATION"] = payload
    else:
        command += ["--duration", payload]

    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )

    assert result.returncode != 0
    assert "Invalid duration" in result.stdout
    assert not marker.exists()


@pytest.mark.parametrize(
    ("invocation", "value", "expected_rc"),
    [("env", "1", 0), ("env", "3600", 0), ("env", "0001", 0),
     ("env", "0008", 0), ("env", "0009", 0), ("env", "0018", 0),
     ("env", "0", 2), ("env", "-1", 2), ("env", "0000", 2),
     ("env", "3601", 2), ("cli", "1", 0), ("cli", "3600", 0),
     ("cli", "0001", 0), ("cli", "0008", 0), ("cli", "0009", 0),
     ("cli", "0018", 0), ("cli", "0", 2), ("cli", "-1", 2),
     ("cli", "", 2), ("cli", "3601", 2)],
)
def test_measure_duration_bounds_before_help(invocation, value, expected_rc):
    env = os.environ.copy()
    command = ["bash", str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh")]
    if invocation == "env":
        env["DURATION"] = value
    else:
        command += ["--duration", value]
    if expected_rc == 0 or invocation == "cli":
        command += ["--help"]

    result = subprocess.run(
        command, cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )

    assert result.returncode == expected_rc


def test_measure_analyze_ignores_invalid_environment_duration(tmp_path):
    samples = tmp_path / "samples.csv"
    samples.write_text("10\n" * 20)
    env = os.environ.copy()
    env["DURATION"] = "abc"
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
            "--analyze",
            str(samples),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert "Invalid duration" not in result.stdout
    assert "Too few samples: 20 < 500" in result.stdout


@pytest.mark.parametrize("minimum", ["0", "1", "-1", "abc"])
def test_measure_analyze_rejects_invalid_minimum_samples(tmp_path, minimum):
    samples = tmp_path / "samples.csv"
    samples.write_text("10\n")
    env = os.environ.copy()
    env["MIN_SAMPLES"] = minimum
    env["DURATION"] = "1"
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
            "--analyze",
            str(samples),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 2
    assert "Invalid MIN_SAMPLES" in result.stdout


@pytest.mark.parametrize("duration", ["1", "300"])
def test_measure_analyze_rejects_minimum_below_duration_floor(tmp_path, duration):
    samples = tmp_path / "samples.csv"
    samples.write_text("")
    env = os.environ.copy()
    env["DURATION"] = duration
    env["MIN_SAMPLES"] = "1"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
         "--analyze", str(samples)],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )

    assert result.returncode == 2
    assert "Invalid MIN_SAMPLES" in result.stdout


def test_measure_analyze_rejects_unrepresentable_minimum_samples(tmp_path):
    samples = tmp_path / "empty.csv"
    samples.write_text("")
    env = os.environ.copy()
    env["DURATION"] = "1"
    env["MIN_SAMPLES"] = "999999999999999999999999999999999999999999"
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
            "--analyze",
            str(samples),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 2
    assert "Invalid MIN_SAMPLES" in result.stdout
    assert "Status:      PASS" not in result.stdout


@pytest.mark.parametrize(
    ("env_duration", "cli_duration", "expected"),
    [("1", None, "PASS"),
     ("300", None, "INCONCLUSIVE"),
     ("300", "1", "PASS"),
     ("300", "300", "INCONCLUSIVE")],
)
def test_measure_analysis_uses_effective_duration(
    tmp_path, env_duration, cli_duration, expected
):
    samples = tmp_path / "samples.csv"
    samples.write_text("10\n" * 20)
    env = os.environ.copy()
    env["DURATION"] = env_duration
    command = [
        "bash", str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
    ]
    if cli_duration is not None:
        command += ["--duration", cli_duration]
    command += ["--analyze", str(samples)]

    result = subprocess.run(
        command, cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )

    assert result.returncode == (0 if expected == "PASS" else 2)
    assert expected in result.stdout


@pytest.mark.parametrize("contents", ["x\n" * 500, "\n" * 500])
def test_measure_analysis_counts_only_numeric_samples(tmp_path, contents):
    samples = tmp_path / "corrupt.csv"
    samples.write_text(contents)
    env = os.environ.copy()
    env["DURATION"] = "300"
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
            "--analyze",
            str(samples),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 2
    if contents.startswith("x"):
        assert "Invalid latency samples: 500" in result.stdout
    else:
        assert "Samples:     0" in result.stdout
    assert "Status:      PASS" not in result.stdout


def test_measure_analysis_rejects_out_of_domain_numeric_sample(tmp_path):
    samples = tmp_path / "out-of-domain.csv"
    samples.write_text("10\n" * 19 + "999999999999999999999999\n")
    env = os.environ.copy()
    env["DURATION"] = "1"
    env["MIN_SAMPLES"] = "20"
    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
            "--analyze",
            str(samples),
        ],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )

    assert result.returncode == 2
    assert "Invalid latency samples: 1" in result.stdout
    assert "Status:      PASS" not in result.stdout


def test_measure_analysis_rejects_invalid_timing_without_silent_filtering(tmp_path):
    samples = tmp_path / "invalid-timing.csv"
    samples.write_text("10\n" * 500 + "-1\n")
    env = os.environ.copy()
    env["DURATION"] = "300"
    env["MIN_SAMPLES"] = "500"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
         "--analyze", str(samples)],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )

    assert result.returncode == 2
    assert "Invalid latency samples: 1" in result.stdout
    assert "Status:      PASS" not in result.stdout


@pytest.mark.parametrize(
    ("count", "minimum", "expected_rc"),
    [(19, "20", 2), (20, "20", 0), (499, "500", 2),
     (500, "500", 0), (1, "2147483647", 2)],
)
def test_measure_minimum_sample_boundaries(tmp_path, count, minimum, expected_rc):
    samples = tmp_path / "boundary.csv"
    samples.write_text("10\n" * count)
    env = os.environ.copy()
    env["DURATION"] = "1" if minimum == "20" else "300"
    env["MIN_SAMPLES"] = minimum
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
         "--analyze", str(samples)],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )

    assert result.returncode == expected_rc
    if minimum == "2147483647":
        assert "Invalid MIN_SAMPLES" not in result.stdout


def test_measure_rejects_minimum_samples_above_representable_max(tmp_path):
    samples = tmp_path / "boundary.csv"
    samples.write_text("")
    env = os.environ.copy()
    env["DURATION"] = "1"
    env["MIN_SAMPLES"] = "2147483648"
    result = subprocess.run(
        ["bash", str(REPO_ROOT / "qos" / "scripts" / "measure-e2e.sh"),
         "--analyze", str(samples)],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
    )

    assert result.returncode == 2
    assert "Invalid MIN_SAMPLES" in result.stdout


@pytest.mark.parametrize("failure_env", [
    {"QOS_EXPORTER_RC": "29", "QOS_FFPROBE_RC": "0"},
    {"QOS_EXPORTER_RC": "0", "QOS_FFPROBE_RC": "29"},
])
def test_lipsync_rejects_independent_tool_failures(isolated_ci_path, failure_env):
    scripts, _, env, tmp_path = isolated_ci_path
    env.update(failure_env)
    env["QOS_FFPROBE_VALID_FRAMES"] = "1"
    result = subprocess.run(
        ["bash", str(scripts / "verify-lipsync.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    report = (tmp_path / "lipsync-report.json").read_text()

    assert result.returncode != 0
    assert '"pass": false' in report
    assert "export/decoder tool failed; measurement unavailable" in result.stdout


def test_lipsync_rejects_empty_frames_with_successful_tools(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = subprocess.run(
        ["bash", str(scripts / "verify-lipsync.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    report = (tmp_path / "lipsync-report.json").read_text()

    assert result.returncode != 0
    assert '"pass": false' in report


@pytest.mark.parametrize("frame_mode", ["video", "audio"])
def test_lipsync_rejects_incomplete_media_frames(isolated_ci_path, frame_mode):
    scripts, _, env, tmp_path = isolated_ci_path
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_FRAME_MODE"] = frame_mode
    result = subprocess.run(
        ["bash", str(scripts / "verify-lipsync.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    report = (tmp_path / "lipsync-report.json").read_text()

    assert result.returncode != 0
    assert '"pass": false' in report


def test_lipsync_accepts_complete_zero_pts_frames(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_FRAME_MODE"] = "zero"
    result = subprocess.run(
        ["bash", str(scripts / "verify-lipsync.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=10, check=False,
    )
    report = json.loads((tmp_path / "lipsync-report.json").read_text())

    assert result.returncode == 0
    assert report["pass"] is True


def test_lipsync_serializes_broadcast_as_json_string(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    env["BROADCAST"] = 'fixture", "injected": true, "tail": "'
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_FFPROBE_FRAME_MODE"] = "zero"
    result = subprocess.run(
        ["bash", str(scripts / "verify-lipsync.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=10, check=False,
    )
    report = json.loads((tmp_path / "lipsync-report.json").read_text())

    assert result.returncode == 0
    assert report["broadcast"] == env["BROADCAST"]
    assert set(report) == {
        "broadcast", "measured_at", "window_sec", "av_offset_ms_avg",
        "av_offset_ms_max", "threshold_ms", "pass",
    }


def test_pts_sync_serializes_broadcast_as_json_string(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    env["BROADCAST"] = 'fixture", "injected": true, "tail": "'
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = subprocess.run(
        ["bash", str(scripts / "verify-pts-sync.sh")],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    report = json.loads((tmp_path / "pts-sync-report.json").read_text())

    assert result.returncode != 0
    assert report["broadcast"] == env["BROADCAST"]
    assert set(report) == {
        "broadcast", "measured_at", "window_sec", "events_sampled",
        "pts_deviation_ms_avg", "pts_deviation_ms_max", "threshold_ms", "pass",
    }


# --- ffprobe timeout margin + sourced helpers must be committable -----------

MIN_FFPROBE_TIMEOUT_MARGIN_SEC = 15


def _install_timeout_recorder(isolated_ci_path):
    """Replace the timeout shim with one that records deadline + argv."""
    scripts, _, env, tmp_path = isolated_ci_path
    record = tmp_path / "timeout-calls.log"
    shim = Path(env["PATH"].split(":")[0]) / "timeout"
    shim.write_text(
        """#!/usr/bin/env bash
deadline="$1"
shift
{ printf '%s\\x1f' "$deadline" "$@"; printf '\\x1e'; } >> "$QOS_TIMEOUT_LOG"
start_ms="${QOS_READINESS_START_MS:-0}"
now_ms="${QOS_READINESS_NOW_MS:-$((start_ms + ${QOS_READINESS_ELAPSED_MS:-0}))}"
if [[ "$1" == "bash" && "$2" == */verify-lipsync.sh && $((now_ms - start_ms)) -ge $((deadline * 1000)) ]]; then
  exit 124
fi
exec "$@"
"""
    )
    shim.chmod(0o755)
    env["QOS_TIMEOUT_LOG"] = str(record)
    return record


def _recorded_timeouts(record):
    calls = []
    for entry in record.read_text().split("\x1e"):
        if entry:
            deadline, *command = entry.rstrip("\x1f").split("\x1f")
            calls.append((int(deadline), command))
    return calls


def _ffprobe_window(command):
    value = command[command.index("-read_intervals") + 1]
    assert value.startswith("%+"), value
    return int(value[2:])


@pytest.mark.parametrize("script", ["verify-lipsync.sh", "verify-pts-sync.sh"])
def test_verify_scripts_give_ffprobe_margin_for_docker_and_moq_join(
    isolated_ci_path, script
):
    scripts, _, env, _ = isolated_ci_path
    record = _install_timeout_recorder(isolated_ci_path)
    env["WINDOW_SEC"] = "15"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    subprocess.run(
        ["bash", str(scripts / script)],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=10, check=False,
    )

    probes = [(d, c) for d, c in _recorded_timeouts(record) if c[:1] == ["ffprobe"]]
    assert len(probes) == 1
    deadline, command = probes[0]
    assert deadline - _ffprobe_window(command) >= MIN_FFPROBE_TIMEOUT_MARGIN_SEC


def test_measure_e2e_ffprobe_margin_and_outer_timeout_ordering(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    record = _install_timeout_recorder(isolated_ci_path)
    env["WINDOW_SEC"] = "15"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["QOS_MEASURE_FRAMES"] = "1"
    subprocess.run(
        ["bash", str(scripts / "integration-test.sh")],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=20, check=False,
    )

    calls = _recorded_timeouts(record)
    outer = [(d, c) for d, c in calls if c[:2] == ["bash", "-c"]]
    inner = [(d, c) for d, c in calls if c[:1] == ["ffprobe"]
             and "compact" in c]
    assert len(outer) == 1 and len(inner) == 1
    outer_deadline, outer_cmd = outer[0]
    inner_deadline, inner_cmd = inner[0]
    window = _ffprobe_window(inner_cmd)
    assert inner_deadline - window >= MIN_FFPROBE_TIMEOUT_MARGIN_SEC
    # The wrapper must outlive ffprobe's own timeout, otherwise it masks it.
    assert outer_deadline > inner_deadline


def _sourced_helpers():
    pattern = re.compile(r'^\s*(?:source|\.)\s+"\$\{SCRIPT_DIR\}/([\w.-]+)"', re.M)
    found = {}
    for script in sorted((REPO_ROOT / "qos" / "scripts").glob("*.sh")):
        for helper in pattern.findall(script.read_text()):
            found.setdefault(helper, []).append(script.name)
    return found


def test_sourced_helpers_are_discovered():
    assert "qos-diagnostics.sh" in _sourced_helpers()


def test_sourced_helpers_and_this_test_are_committable():
    """A clean checkout only contains tracked files: helpers must be tracked
    (or at least staged/untracked-but-not-ignored, i.e. committable)."""
    if not (REPO_ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard",
         "--", "qos/scripts"],
        cwd=REPO_ROOT, text=True, stdout=subprocess.PIPE, check=True,
    ).stdout.split()
    committable = {Path(p).name for p in listed}
    required = set(_sourced_helpers()) | {Path(__file__).name}

    assert required <= committable, sorted(required - committable)


# === Ronda 2: exit 124, margen derivado, gate coherente, WINDOW_SEC, redactor, EPIPE ===

GATE_SLACK_SEC = 10
MARGIN_SCRIPTS = ["verify-lipsync.sh", "verify-pts-sync.sh", "measure-e2e.sh"]


def _run(scripts, env, script, timeout=20):
    return subprocess.run(
        ["bash", str(scripts / script)],
        cwd=REPO_ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        timeout=timeout, check=False,
    )


def _recent_catalog_wall():
    """clock.wall (us since 2020-01-01) placing the stream start just now, so
    shimmed frames yield a latency inside the accepted 0..60000 ms range."""
    import time
    return str((int(time.time() * 1000) - 100) * 1000 - 1_577_836_800_000_000)


def _set_margin_constant(scripts, value):
    path = scripts / "qos-diagnostics.sh"
    text = path.read_text()
    patched = re.sub(
        r"^QOS_FFPROBE_TIMEOUT_MARGIN_SEC=\d+",
        f"QOS_FFPROBE_TIMEOUT_MARGIN_SEC={value}",
        text, flags=re.M,
    )
    assert patched != text
    path.write_text(patched)


def _probe_margins(isolated_ci_path, script, window=15):
    """Run `script` and return deadline - window for each capture ffprobe."""
    scripts, _, env, _ = isolated_ci_path
    record = _install_timeout_recorder(isolated_ci_path)
    env["WINDOW_SEC"] = str(window)
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    entry = script
    if script == "measure-e2e.sh":
        env["QOS_MEASURE_FRAMES"] = "1"
        entry = "integration-test.sh"
    _run(scripts, env, entry)
    probes = [(d, c) for d, c in _recorded_timeouts(record) if c[:1] == ["ffprobe"]]
    if script == "measure-e2e.sh":
        probes = [(d, c) for d, c in probes if "compact" in c]
    assert probes, "no ffprobe invocation was recorded"
    return [d - _ffprobe_window(c) for d, c in probes]


# --- A1: ffprobe exit 124 stays a tool error ---------------------------------

def test_lipsync_treats_ffprobe_timeout_124_as_tool_error(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    env.update(QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="124",
               QOS_FFPROBE_FRAME_MODE="zero")
    result = _run(scripts, env, "verify-lipsync.sh", timeout=10)
    report = json.loads((tmp_path / "lipsync-report.json").read_text())

    assert result.returncode != 0
    assert report["pass"] is False
    assert "[QOS-DIAGNOSTIC] stage=ffprobe exit=124" in result.stdout
    assert "export/decoder tool failed; measurement unavailable" in result.stdout


def test_pts_sync_treats_ffprobe_timeout_124_as_tool_error(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    env.update(QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="124",
               QOS_FFPROBE_FRAME_MODE="zero")
    result = _run(scripts, env, "verify-pts-sync.sh", timeout=10)

    assert result.returncode != 0
    assert "[QOS-DIAGNOSTIC] stage=ffprobe exit=124" in result.stdout
    assert "exporter/decoder tool failure" in result.stdout


def test_measure_treats_ffprobe_timeout_124_as_tool_error(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    env.update(QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="124", QOS_MEASURE_FRAMES="1")
    result = _run(scripts, env, "integration-test.sh")

    assert "[QOS-DIAGNOSTIC] stage=ffprobe exit=124" in result.stdout
    assert "Exporter/decoder failed; latency measurement unavailable" in result.stdout
    assert "Capturadas" not in result.stdout
    assert "[INTEGRATION] ✓ PASS: Latencia" not in result.stdout
    assert result.returncode != 0


# --- A2/A3: margin is derived from the constant, never a literal, not overridable

_TIMEOUT_FFPROBE = re.compile(
    r'\btimeout\s+(?P<arg>"[^"\n]*"|\$\(\(.*?\)\)|\S+)\s+ffprobe\b'
)


def _ffprobe_timeout_sites():
    sites = []
    for script in sorted((REPO_ROOT / "qos" / "scripts").glob("*.sh")):
        text = script.read_text().replace("\\\n", " ")
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        for match in _TIMEOUT_FFPROBE.finditer(code):
            sites.append((script, match.group("arg"), code))
    return sites


def test_scan_finds_every_known_ffprobe_timeout_site():
    scanned = {script.name for script, _, _ in _ffprobe_timeout_sites()}
    assert set(MARGIN_SCRIPTS) <= scanned


def test_every_ffprobe_timeout_derives_margin_from_the_constant():
    offenders = []
    for script, arg, code in _ffprobe_timeout_sites():
        uses_constant = "QOS_FFPROBE_TIMEOUT_MARGIN_SEC" in arg
        # bash -c wrappers receive it as a positional argument
        uses_positional = re.search(r"\$\d", arg) and re.search(
            r'"\$QOS_FFPROBE_TIMEOUT_MARGIN_SEC"', code
        )
        literal = re.fullmatch(r"\d+", arg) or re.search(r"\+\s*\d", arg)
        sources_helper = 'qos-diagnostics.sh"' in code
        if literal or not (uses_constant or uses_positional) or not sources_helper:
            offenders.append(f"{script.name}: timeout {arg} ffprobe")
    assert not offenders, offenders


@pytest.mark.parametrize("script", MARGIN_SCRIPTS)
def test_ffprobe_margin_follows_the_constant_not_a_literal(isolated_ci_path, script):
    scripts, _, _, _ = isolated_ci_path
    _set_margin_constant(scripts, 37)

    assert set(_probe_margins(isolated_ci_path, script)) == {37}


@pytest.mark.parametrize("script", MARGIN_SCRIPTS)
def test_ffprobe_margin_constant_is_not_overridable_from_environment(
    isolated_ci_path, script
):
    _, _, env, _ = isolated_ci_path
    env["QOS_FFPROBE_TIMEOUT_MARGIN_SEC"] = "5"

    assert set(_probe_margins(isolated_ci_path, script)) == {
        MIN_FFPROBE_TIMEOUT_MARGIN_SEC
    }


# --- B: the readiness gate always outlives ffprobe's own timeout --------------

@pytest.mark.parametrize("window", [5, 15, 30])
def test_readiness_gate_timeout_exceeds_inner_ffprobe_timeout(
    isolated_ci_path, window
):
    scripts, _, env, _ = isolated_ci_path
    record = _install_timeout_recorder(isolated_ci_path)
    env.update(WINDOW_SEC=str(window), QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="0")
    _run(scripts, env, "integration-test.sh")

    calls = _recorded_timeouts(record)
    gate_index = next(
        i for i, (_, c) in enumerate(calls)
        if c[:1] == ["bash"] and c[1].endswith("/verify-lipsync.sh")
    )
    gate_deadline = calls[gate_index][0]
    inner_deadline = next(
        d for d, c in calls[gate_index + 1:] if c[:1] == ["ffprobe"]
    )

    assert gate_deadline > inner_deadline
    assert gate_deadline == window + MIN_FFPROBE_TIMEOUT_MARGIN_SEC + GATE_SLACK_SEC


def test_readiness_gate_does_not_mask_ffprobe_timeout_as_data_path_failure(
    isolated_ci_path,
):
    """WINDOW_SEC=15 made ffprobe's timeout (30) equal the old gate (30): the
    gate killed first and the tool error was classified DATA_PATH_FAILURE."""
    scripts, _, env, _ = isolated_ci_path
    env.update(WINDOW_SEC="15", QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="0",
               QOS_READINESS_FFPROBE_RC="124", QOS_FFPROBE_VALID_FRAMES="1",
               QOS_READINESS_FORCE_VALID="1")
    # Elapsed time sits exactly at ffprobe's timeout (30 s), before the gate's.
    env.update(QOS_READINESS_START_MS="100000", QOS_READINESS_NOW_MS="130000")
    result = _run(scripts, env, "integration-test.sh")

    assert "[QOS-DIAGNOSTIC] stage=ffprobe exit=124" in result.stdout
    assert "Media readiness TOOL_ERROR" in result.stdout
    assert "DATA_PATH_FAILURE" not in result.stdout


# --- C1: WINDOW_SEC is validated before any shell arithmetic -------------------

@pytest.mark.parametrize("script", [
    "verify-lipsync.sh", "verify-pts-sync.sh", "integration-test.sh",
])
def test_window_sec_command_substitution_is_never_evaluated(
    isolated_ci_path, script
):
    scripts, _, env, tmp_path = isolated_ci_path
    marker = tmp_path / "window-injection-marker"
    env["WINDOW_SEC"] = f"x[$(touch {marker})]"
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = _run(scripts, env, script, timeout=10)

    assert not marker.exists()
    assert result.returncode != 0
    assert "Invalid WINDOW_SEC" in result.stdout


@pytest.mark.parametrize("value", [
    "0", "-5", "abc", "1.5", "1 2", "0x10", "3601", "99999", "5\n", "00000",
])
@pytest.mark.parametrize("script", [
    "verify-lipsync.sh", "verify-pts-sync.sh", "integration-test.sh",
])
def test_window_sec_rejects_values_outside_decimal_1_to_3600(
    isolated_ci_path, script, value
):
    scripts, docker_log, env, _ = isolated_ci_path
    env["WINDOW_SEC"] = value
    result = _run(scripts, env, script, timeout=10)

    assert result.returncode != 0
    assert "Invalid WINDOW_SEC" in result.stdout
    assert not docker_log.exists() or "export ts" not in docker_log.read_text()


@pytest.mark.parametrize(("value", "decimal"), [("08", 8), ("010", 10), ("0015", 15)])
def test_window_sec_leading_zeros_are_decimal_not_octal(
    isolated_ci_path, value, decimal
):
    scripts, _, env, _ = isolated_ci_path
    record = _install_timeout_recorder(isolated_ci_path)
    env.update(WINDOW_SEC=value, QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="0")
    result = _run(scripts, env, "verify-lipsync.sh", timeout=10)

    assert "value too great for base" not in result.stdout
    (deadline, command), = [
        (d, c) for d, c in _recorded_timeouts(record) if c[:1] == ["ffprobe"]
    ]
    assert _ffprobe_window(command) == decimal
    assert deadline == decimal + MIN_FFPROBE_TIMEOUT_MARGIN_SEC


# --- C2/C3/C4: diagnostic redactor ---------------------------------------------

def _redact(tmp_path, payload, timeout=20):
    """Run the redactor in its own process group: on timeout the python
    grandchild is killed too instead of spinning on after the test."""
    import signal
    stderr_file = tmp_path / "redact-input.txt"
    stderr_file.write_bytes(payload if isinstance(payload, bytes) else payload.encode())
    proc = subprocess.Popen(
        ["bash", "-c", 'source "$1"; qos_report_tool_diagnostic exporter 1 "$2"',
         "bash", str(REPO_ROOT / "qos" / "scripts" / "qos-diagnostics.sh"),
         str(stderr_file)],
        text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()
        pytest.fail(f"redactor exceeded {timeout}s on {len(payload)} chars of input")
    return subprocess.CompletedProcess(proc.args, proc.returncode, out, err)


@pytest.mark.parametrize(("diagnostic", "sentinel"), [
    ('{"id_token":"fixture_id_token_value"}', "fixture_id_token_value"),
    ("auth_token: fixture_auth_token_value", "fixture_auth_token_value"),
    ("session_token=fixture_session_token_value", "fixture_session_token_value"),
    ('{"sessionToken":"fixture_camel_session_value"}', "fixture_camel_session_value"),
    ("secret_key=fixture_secret_key_value", "fixture_secret_key_value"),
    ("cluster_token=fixture_cluster_token_value", "fixture_cluster_token_value"),
    ("AWS_SECRET_ACCESS_KEY=fixture_aws_value", "fixture_aws_value"),
    ('{"clientSecret":"fixture_client_secret_value"}', "fixture_client_secret_value"),
    ('{"apiKey":"fixture_api_key_value"}', "fixture_api_key_value"),
    ("GET /export?jwt=fixture_jwt_query_value&track=video", "fixture_jwt_query_value"),
    ('{"jwt":"fixture_jwt_json_value"}', "fixture_jwt_json_value"),
    ("jwt: fixture_jwt_header_value", "fixture_jwt_header_value"),
    ("GET /export?access_token=fixture_query_access_value&x=1", "fixture_query_access_value"),
])
def test_redactor_covers_compound_keys_and_jwt(tmp_path, diagnostic, sentinel):
    result = _redact(tmp_path, diagnostic + "\n")

    assert result.returncode == 0
    assert sentinel not in result.stderr
    assert "[REDACTED]" in result.stderr


@pytest.mark.parametrize(("diagnostic", "sentinels"), [
    ('token="fixture_quoted_value"', ("fixture_quoted_value",)),
    ("password = 'fixture x y'", ("fixture x y", "x y'")),
    ('{\\"password\\":\\"fixture_hunter2\\"}', ("fixture_hunter2",)),
    ('{\\"token\\": \\"fixture_escaped_token\\", \\"ok\\": 1}', ("fixture_escaped_token",)),
    ('{"password": "fixture_truncated', ("fixture_truncated",)),
    ("{'secret': 'fixture_trunc_single", ("fixture_trunc_single",)),
    ('{\\"password\\":\\"fixture_trunc_escaped', ("fixture_trunc_escaped",)),
    ('\x1b[3mtoken\x1b[0m\x1b[2m=\x1b[0mfixture_ansi_value', ("fixture_ansi_value",)),
])
def test_redactor_covers_logfmt_quotes_escaped_and_truncated_json(
    tmp_path, diagnostic, sentinels
):
    result = _redact(tmp_path, diagnostic + "\n")

    assert result.returncode == 0
    assert all(s not in result.stderr for s in sentinels), result.stderr
    assert "[REDACTED]" in result.stderr


def test_redactor_keeps_benign_diagnostics_readable(tmp_path):
    payload = (
        "\x1b[32m INFO\x1b[0m connected peer=tcp://moq-relay:4444 quality=low\n"
        "write /dev/stdout: broken pipe\n"
    )
    result = _redact(tmp_path, payload)

    assert result.returncode == 0
    assert "peer=tcp://moq-relay:4444 quality=low" in result.stderr
    assert "write /dev/stdout: broken pipe" in result.stderr
    assert "\x1b" not in result.stderr
    assert "[REDACTED]" not in result.stderr


@pytest.mark.parametrize("env_extra", [{}, {"LC_ALL": "C", "PYTHONIOENCODING": "ascii"}])
def test_redactor_survives_non_utf8_bytes(tmp_path, env_extra):
    payload = b"bad \xff\xfe bytes token=fixture_binary_value\n"
    stderr_file = tmp_path / "binary.txt"
    stderr_file.write_bytes(payload)
    env = os.environ.copy()
    env.update(env_extra)
    result = subprocess.run(
        ["bash", "-c", 'source "$1"; qos_report_tool_diagnostic exporter 1 "$2"',
         "bash", str(REPO_ROOT / "qos" / "scripts" / "qos-diagnostics.sh"),
         str(stderr_file)],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        timeout=20, check=False,
    )

    assert result.returncode == 0
    assert b"fixture_binary_value" not in result.stderr
    assert b"token=[REDACTED]" in result.stderr


@pytest.mark.parametrize("shape", [
    "a" * 60000,
    "http://u:" + "a" * 60000,
    "?sig=" + "x" * 60000,
    "\\" * 60000,
    "token:" * 10000,
    '"token' * 10000,
    "a." * 30000,
])
def test_redactor_runtime_is_bounded_on_adversarial_input(tmp_path, shape):
    import time
    started = time.monotonic()
    result = _redact(tmp_path, shape + "\n")

    assert result.returncode == 0
    assert time.monotonic() - started < 5


# --- D1: tolerate only the exporter's EPIPE after ffprobe closed the pipe ------

EPIPE_STDERR = (
    "\\x1b[32m INFO\\x1b[0m connected peer=tcp://moq-relay:4444\\n"
    "\\x1b[33m WARN\\x1b[0m UDP receive buffer is smaller than requested\\n"
    "write /dev/stdout: broken pipe"
)


def _epipe_env(env, **overrides):
    env.update(QOS_EXPORTER_RC="1", QOS_FFPROBE_RC="0", QOS_EXPORTER_DATA="1",
               QOS_EXPORTER_STDERR=EPIPE_STDERR, QOS_FFPROBE_FRAME_MODE="zero")
    env.update(overrides)


def test_lipsync_tolerates_exporter_epipe_when_ffprobe_succeeded(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    _epipe_env(env)
    result = _run(scripts, env, "verify-lipsync.sh", timeout=10)
    report = json.loads((tmp_path / "lipsync-report.json").read_text())

    assert result.returncode == 0, result.stdout
    assert report["pass"] is True
    assert "broken-pipe-tolerated" in result.stdout
    assert "[QOS-DIAGNOSTIC] stage=exporter exit=0" in result.stdout


def test_pts_sync_tolerates_exporter_epipe_when_ffprobe_succeeded(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    _epipe_env(env)
    result = _run(scripts, env, "verify-pts-sync.sh", timeout=10)

    assert "exporter/decoder tool failure" not in result.stdout
    assert "[QOS-DIAGNOSTIC] stage=exporter exit=0" in result.stdout
    assert "broken-pipe-tolerated" in result.stdout


def test_measure_tolerates_exporter_epipe_when_ffprobe_succeeded(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    _epipe_env(env, QOS_MEASURE_FRAMES="1", QOS_CATALOG_WALL=_recent_catalog_wall())
    result = _run(scripts, env, "integration-test.sh")

    assert "Exporter/decoder failed; latency measurement unavailable" not in result.stdout
    assert "Capturadas 1 muestras" in result.stdout
    assert "broken-pipe-tolerated" in result.stdout


@pytest.mark.parametrize(("overrides", "raw_exit"), [
    ({"QOS_FFPROBE_RC": "29"}, "1"),                       # ffprobe failed too
    ({"QOS_EXPORTER_STDERR": "Error: connection refused"}, "1"),   # other error
    ({"QOS_EXPORTER_STDERR": "\\x1b[31mERROR\\x1b[0m boom\\n" + EPIPE_STDERR}, "1"),
    ({"QOS_EXPORTER_STDERR": "write /dev/stdout: broken pipe\\nError: later"}, "1"),
    ({"QOS_EXPORTER_RC": "37"}, "37"),                     # not the exporter's EPIPE exit
    ({"QOS_EXPORTER_STDERR": ""}, "1"),                    # no broken pipe evidence
])
@pytest.mark.parametrize("script", ["verify-lipsync.sh", "verify-pts-sync.sh"])
def test_exporter_failure_is_not_tolerated_unless_pure_epipe(
    isolated_ci_path, script, overrides, raw_exit
):
    scripts, _, env, _ = isolated_ci_path
    _epipe_env(env, **overrides)
    result = _run(scripts, env, script, timeout=10)

    assert result.returncode != 0
    assert f"[QOS-DIAGNOSTIC] stage=exporter exit={raw_exit}" in result.stdout
    assert "broken-pipe-tolerated" not in result.stdout
    assert "tool fail" in result.stdout


def test_measure_does_not_tolerate_epipe_when_ffprobe_failed(isolated_ci_path):
    scripts, _, env, _ = isolated_ci_path
    _epipe_env(env, QOS_FFPROBE_RC="29", QOS_MEASURE_FRAMES="1")
    result = _run(scripts, env, "integration-test.sh")

    assert "Exporter/decoder failed; latency measurement unavailable" in result.stdout
    assert "broken-pipe-tolerated" not in result.stdout


def test_epipe_with_zero_frames_still_fails_as_data_path_not_tool_error(
    isolated_ci_path,
):
    scripts, _, env, _ = isolated_ci_path
    _epipe_env(env, QOS_FFPROBE_FRAME_MODE="", QOS_READINESS_FORCE_VALID="0",
               QOS_READINESS_EXPORTER_RC="1", QOS_READINESS_FFPROBE_RC="0")
    result = _run(scripts, env, "integration-test.sh")

    assert "broken-pipe-tolerated" in result.stdout
    assert "Media readiness DATA_PATH_FAILURE" in result.stdout
    assert "Media readiness READY" not in result.stdout
    assert result.returncode != 0


def test_lipsync_epipe_with_zero_frames_is_a_failure(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    _epipe_env(env, QOS_FFPROBE_FRAME_MODE="")
    result = _run(scripts, env, "verify-lipsync.sh", timeout=10)
    report = json.loads((tmp_path / "lipsync-report.json").read_text())

    assert result.returncode != 0
    assert report["pass"] is False
    assert "incomplete media frames" in result.stdout


# --- D2: `date +%N` with leading zero must not be parsed as octal -------------

def test_lipsync_timestamp_survives_nanoseconds_with_leading_zero(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    shim = Path(env["PATH"].split(":")[0]) / "date"
    shim.write_text(
        '#!/usr/bin/env bash\n'
        'for arg in "$@"; do [[ "$arg" == "+%N" ]] && { echo 089999999; exit 0; }; done\n'
        'exec /bin/date "$@"\n'
    )
    shim.chmod(0o755)
    env.update(QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="0", QOS_FFPROBE_FRAME_MODE="zero")
    result = _run(scripts, env, "verify-lipsync.sh", timeout=10)
    report = json.loads((tmp_path / "lipsync-report.json").read_text())

    assert "value too great for base" not in result.stdout
    assert result.returncode == 0
    assert report["measured_at"]["unix_ms"] % 1000 == 89


# --- D3 exception: measure-e2e EXIT trap must not hit an unbound `run_dir` ----

def test_measure_exit_trap_cleans_run_dir_without_unbound_variable(isolated_ci_path):
    scripts, _, env, tmp_path = isolated_ci_path
    env.update(QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="0", QOS_MEASURE_FRAMES="1",
               QOS_CATALOG_WALL=_recent_catalog_wall())
    result = _run(scripts, env, "integration-test.sh")

    assert "Capturadas 1 muestras" in result.stdout
    assert "unbound variable" not in result.stdout
    assert list(tmp_path.glob("qos-measure.*")) == []


# === Ronda 3: redactor fail-closed, magnitud del timeout externo, ReDoS, aritmética ===

def _redacted_lines(tmp_path, payload):
    result = _redact(tmp_path, payload)
    assert result.returncode == 0, result.stderr
    header, _, body = result.stderr.partition("\n")
    assert header == "[QOS-DIAGNOSTIC] stage=exporter exit=1", header
    return body


# --- R3.1 (CRITICAL): comilla sin cierre => redactar hasta el FINAL DEL TEXTO ---

@pytest.mark.parametrize(("diagnostic", "sentinels"), [
    ('starting export...\n{"private_key":"-----BEGIN PRIVATE KEY-----\n'
     'fixture_MIIEvQ_secretkeyline1\nfixture_anothersecretkeyline2\n'
     '-----END PRIVATE KEY-----\n',
     ("fixture_MIIEvQ_secretkeyline1", "fixture_anothersecretkeyline2")),
    ('{"password":"fixture_dq_l1\nfixture_dq_l2\nfixture_dq_l3\n',
     ("fixture_dq_l1", "fixture_dq_l2", "fixture_dq_l3")),
    ("{'secret': 'fixture_sq_l1\nfixture_sq_l2\nfixture_sq_l3\n",
     ("fixture_sq_l1", "fixture_sq_l2", "fixture_sq_l3")),
    ('{\\"token\\":\\"fixture_esc_l1\nfixture_esc_l2\nfixture_esc_l3\n',
     ("fixture_esc_l1", "fixture_esc_l2", "fixture_esc_l3")),
    ('token: "fixture_mid_l1\nfixture_mid_l2"\nfixture_mid_l3\n',
     ("fixture_mid_l1", "fixture_mid_l2", "fixture_mid_l3")),
])
def test_redactor_unclosed_quote_redacts_to_end_of_text(
    tmp_path, diagnostic, sentinels
):
    stderr = _redacted_lines(tmp_path, diagnostic)

    assert all(s not in stderr for s in sentinels), stderr
    assert "[REDACTED]" in stderr


def test_redactor_unclosed_quote_keeps_text_before_the_key(tmp_path):
    stderr = _redacted_lines(
        tmp_path, 'starting export...\n{"password":"fixture_l1\nfixture_l2\n')

    assert "[exporter] starting export..." in stderr


@pytest.mark.parametrize(("pem_label"), [
    "PRIVATE KEY", "RSA PRIVATE KEY", "EC PRIVATE KEY",
    "ENCRYPTED PRIVATE KEY", "OPENSSH PRIVATE KEY", "PGP PRIVATE KEY BLOCK",
])
def test_redactor_redacts_whole_pem_block_without_a_sensitive_key(tmp_path, pem_label):
    payload = (
        "before_visible\n"
        f"-----BEGIN {pem_label}-----\n"
        "fixture_pem_line1\nfixture_pem_line2\nfixture_pem_line3\n"
        f"-----END {pem_label}-----\n"
        "after_visible\n"
    )
    stderr = _redacted_lines(tmp_path, payload)

    assert all(f"fixture_pem_line{i}" not in stderr for i in (1, 2, 3)), stderr
    assert "BEGIN" not in stderr or "[REDACTED]" in stderr
    assert "[exporter] before_visible" in stderr
    assert "[exporter] after_visible" in stderr


def test_redactor_pem_begin_without_end_redacts_to_end_of_text(tmp_path):
    payload = (
        "before_visible\n-----BEGIN OPENSSH PRIVATE KEY-----\n"
        "fixture_pem_line1\nfixture_pem_line2\nfixture_pem_line3\n"
    )
    stderr = _redacted_lines(tmp_path, payload)

    assert all(f"fixture_pem_line{i}" not in stderr for i in (1, 2, 3)), stderr
    assert "[exporter] before_visible" in stderr


def test_redactor_pem_inside_one_line_json_with_literal_backslash_n(tmp_path):
    payload = ('{"note":"-----BEGIN PRIVATE KEY-----\\nfixture_pem_inline\\n'
               '-----END PRIVATE KEY-----\\n","ok":1}\n')
    stderr = _redacted_lines(tmp_path, payload)

    assert "fixture_pem_inline" not in stderr


def test_redactor_leaves_public_material_readable(tmp_path):
    payload = ("-----BEGIN PUBLIC KEY-----\nfixture_public_line\n"
               "-----END PUBLIC KEY-----\n")
    stderr = _redacted_lines(tmp_path, payload)

    assert "fixture_public_line" in stderr
    assert "[REDACTED]" not in stderr


# --- R3.2 (HIGH): valor no entrecomillado/cerrado => hasta fin de línea ---------

@pytest.mark.parametrize(("diagnostic", "sentinels"), [
    ('token: Some("fixture_x")', ("fixture_x", '")')),
    ('{"tokens":["fixture_a1","fixture_b2"]}', ("fixture_a1", "fixture_b2", '"]')),
    ("private_key: [12, 255, 3, 9]", ("255", "3, 9]")),
    ("token=fixture_semi;fixture_tail", ("fixture_semi", "fixture_tail")),
    ('{"credentials":{"user":"fixture_u","pw":"fixture_pw"}}',
     ("fixture_u", "fixture_pw", '"pw"')),
    ("password: fixture_a, fixture_b; fixture_c } fixture_d",
     ("fixture_a", "fixture_b", "fixture_c", "fixture_d")),
])
def test_redactor_unquoted_or_wrapped_value_is_redacted_to_end_of_line(
    tmp_path, diagnostic, sentinels
):
    stderr = _redacted_lines(tmp_path, diagnostic + "\n")

    assert all(s not in stderr for s in sentinels), stderr
    assert "[REDACTED]" in stderr


def test_redactor_end_of_line_redaction_does_not_swallow_next_line(tmp_path):
    stderr = _redacted_lines(
        tmp_path, "token: Some(fixture_x)\nnext_line_visible\n")

    assert "fixture_x" not in stderr
    assert "[exporter] next_line_visible" in stderr


@pytest.mark.parametrize(("diagnostic", "expected"), [
    ('token="fixture_a" next="keep"', '[exporter] token="[REDACTED]" next="keep"'),
    ("x token='fixture_a' next='keep'", "[exporter] x token='[REDACTED]' next='keep'"),
    ("GET /x?token=fixture_q&y=1 ok", "[exporter] GET /x?token=[REDACTED]&y=1 ok"),
    ("GET /x?a=1&sig=fixture_s#frag", "[exporter] GET /x?a=1&sig=[REDACTED]#frag"),
])
def test_redactor_closed_quotes_and_query_strings_redact_only_the_value(
    tmp_path, diagnostic, expected
):
    stderr = _redacted_lines(tmp_path, diagnostic + "\n")

    assert stderr.strip() == expected


def test_redactor_query_value_in_quotes_is_not_left_behind(tmp_path):
    stderr = _redacted_lines(tmp_path, 'GET /x?token="fixture_qq"&y=1\n')

    assert "fixture_qq" not in stderr


# --- R3.3 (HIGH): magnitud EXACTA del timeout externo de measure-e2e -----------

def _set_slack_constant(scripts, value):
    path = scripts / "qos-diagnostics.sh"
    text = path.read_text()
    patched = re.sub(
        r"^QOS_GATE_TIMEOUT_SLACK_SEC=\d+",
        f"QOS_GATE_TIMEOUT_SLACK_SEC={value}",
        text, flags=re.M,
    )
    assert patched != text
    path.write_text(patched)


def _measure_outer_timeout(isolated_ci_path, window):
    scripts, _, env, _ = isolated_ci_path
    record = _install_timeout_recorder(isolated_ci_path)
    env.update(WINDOW_SEC=str(window), QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="0",
               QOS_MEASURE_FRAMES="1")
    _run(scripts, env, "integration-test.sh")
    outer = [d for d, c in _recorded_timeouts(record) if c[:2] == ["bash", "-c"]]
    assert len(outer) == 1
    return outer[0]


@pytest.mark.parametrize("window", [5, 15, 30])
def test_measure_outer_timeout_is_exactly_duration_plus_margin_plus_slack(
    isolated_ci_path, window
):
    outer = _measure_outer_timeout(isolated_ci_path, window)

    assert outer == window + MIN_FFPROBE_TIMEOUT_MARGIN_SEC + GATE_SLACK_SEC


def test_measure_outer_timeout_slack_follows_the_constant_not_a_literal(
    isolated_ci_path,
):
    scripts, _, _, _ = isolated_ci_path
    _set_slack_constant(scripts, 37)
    outer = _measure_outer_timeout(isolated_ci_path, 15)

    assert outer == 15 + MIN_FFPROBE_TIMEOUT_MARGIN_SEC + 37


_TIMEOUT_ARITH = re.compile(r'\btimeout\s+"?\$\(\((?P<expr>[^)]*)\)\)"?')


def _timeout_arithmetic_sites():
    sites = []
    for script in sorted((REPO_ROOT / "qos" / "scripts").glob("*.sh")):
        text = script.read_text().replace("\\\n", " ")
        code = "\n".join(
            line for line in text.splitlines() if not line.lstrip().startswith("#")
        )
        for match in _TIMEOUT_ARITH.finditer(code):
            sites.append((script.name, match.group("expr")))
    return sites


def test_timeout_arithmetic_scan_finds_the_known_sites():
    scanned = {name for name, _ in _timeout_arithmetic_sites()}
    assert {"measure-e2e.sh", "verify-lipsync.sh", "verify-pts-sync.sh"} <= scanned


def test_no_timeout_arithmetic_in_qos_scripts_has_a_numeric_literal():
    literal = re.compile(r"(?<![\w$])\d+(?!\w)")
    offenders = [(name, expr) for name, expr in _timeout_arithmetic_sites()
                 if literal.search(expr)]

    assert not offenders, offenders


# --- R3.4 (MEDIUM): redactor lineal ----------------------------------------------

# ids explícitos: pytest exporta el id en PYTEST_CURRENT_TEST y un payload de
# 200k caracteres en el id desbordaría el límite de entorno de execve.
@pytest.mark.parametrize("shape", [
    pytest.param("token" * 40000, id="token-repeated"),
    pytest.param("?" + "token" * 40000, id="query-token-repeated"),
    pytest.param("a" * 200000, id="plain-word"),
    pytest.param("token:" * 30000, id="token-colon-repeated"),
    pytest.param("&" + "sig" * 60000, id="query-sig-repeated"),
    pytest.param("?" + "key" * 60000, id="query-key-repeated"),
])
def test_redactor_is_linear_on_200k_char_inputs(tmp_path, shape):
    import time
    started = time.monotonic()
    result = _redact(tmp_path, shape + "\n", timeout=30)
    elapsed = time.monotonic() - started

    assert result.returncode == 0
    assert elapsed < 3, f"{elapsed:.1f}s"


# --- R3.5 (MEDIUM): userinfo con usuario vacío -----------------------------------

@pytest.mark.parametrize(("diagnostic", "sentinel"), [
    ("redis://:fixture_pw@cache:6379/0", "fixture_pw"),
    ("amqp://:fixture_pw@host/", "fixture_pw"),
    ("amqp://:fixture_pw@host", "fixture_pw"),
])
def test_redactor_redacts_userinfo_with_empty_user(tmp_path, diagnostic, sentinel):
    stderr = _redacted_lines(tmp_path, diagnostic + "\n")

    assert sentinel not in stderr
    assert "[REDACTED]@" in stderr


@pytest.mark.parametrize("diagnostic", [
    "https://host/path@x",
    "https://host:8080/a@b/c",
    "http://:8080/path@x",
    "see https://example.test/users/@me and more",
])
def test_redactor_does_not_mangle_urls_without_real_userinfo(tmp_path, diagnostic):
    stderr = _redacted_lines(tmp_path, diagnostic + "\n")

    assert stderr.strip() == f"[exporter] {diagnostic}"


# --- R3.6a: más stems (DRM) sin falsos positivos ---------------------------------

@pytest.mark.parametrize(("diagnostic", "sentinel"), [
    ("pwd=fixture_v_pwd", "fixture_v_pwd"),
    ("DB_PWD: fixture_v_dbpwd", "fixture_v_dbpwd"),
    ("pass=fixture_v_pass", "fixture_v_pass"),
    ("db_pass=fixture_v_dbpass", "fixture_v_dbpass"),
    ("userPass: fixture_v_userpass", "fixture_v_userpass"),
    ("passphrase: fixture_v_passphrase", "fixture_v_passphrase"),
    ("psk=fixture_v_psk", "fixture_v_psk"),
    ("Cookie: sid=fixture_v_cookie; theme=dark", "fixture_v_cookie"),
    ("Set-Cookie: sid=fixture_v_setcookie; Path=/", "fixture_v_setcookie"),
    ("otp=fixture_v_otp", "fixture_v_otp"),
    ("signing_key=fixture_v_signing", "fixture_v_signing"),
    ("MASTER_KEY=fixture_v_master", "fixture_v_master"),
    ("content_key: fixture_v_content", "fixture_v_content"),
    ('{"streamKey":"fixture_v_stream"}', "fixture_v_stream"),
    ("drm.content-key=fixture_v_dotted", "fixture_v_dotted"),
])
def test_redactor_covers_drm_and_compound_key_stems(tmp_path, diagnostic, sentinel):
    stderr = _redacted_lines(tmp_path, diagnostic + "\n")

    assert sentinel not in stderr
    assert "[REDACTED]" in stderr


def test_redactor_does_not_redact_key_lookalikes(tmp_path):
    payload = ("keyframe=fixture_kf keyint=60 key_frame=2 monkey=3 bypass=on "
               "passed=true hotpath=1 keys=2 sort=asc\n")
    stderr = _redacted_lines(tmp_path, payload)

    assert stderr.strip() == f"[exporter] {payload.strip()}"


# --- R3.6b: OSC y caracteres de control ------------------------------------------

@pytest.mark.parametrize(("payload", "keeps_tail"), [
    ("\x1b]0;token=fixture_osc_bel\x07visible", True),
    ("\x1b]8;;https://fixture.example/?token=fixture_osc_bel\x1b\\visible", True),
    ("\x1b]0;token=fixture_osc_bel visible", False),  # sin terminador: hasta fin de línea
])
def test_redactor_strips_osc_sequences(tmp_path, payload, keeps_tail):
    stderr = _redacted_lines(tmp_path, payload + "\n")

    assert "fixture_osc_bel" not in stderr
    assert "\x1b" not in stderr and "\x07" not in stderr
    assert ("visible" in stderr) is keeps_tail


def test_redactor_strips_c0_controls_but_keeps_newline_and_tab(tmp_path):
    payload = ("a\x00b\x07c\x08d\x0be\x0cf\x1ag\x7fh\x9bi\tj\n"
               "to\x00ken=fixture_ctl_split\n")
    stderr = _redacted_lines(tmp_path, payload)

    assert "[exporter] abcdefghi\tj" in stderr
    assert "fixture_ctl_split" not in stderr
    forbidden = [c for c in stderr if (ord(c) < 32 and c not in "\n\t")
                 or 0x7f <= ord(c) <= 0x9f]
    assert not forbidden, forbidden


# --- R3.6c: el stderr de herramientas no puede forjar el diagnóstico -------------

def _stub_verify_lipsync_for_gate(isolated_ci_path, body):
    scripts, _, env, _ = isolated_ci_path
    (scripts / "verify-lipsync.sh").write_text(f"#!/usr/bin/env bash\n{body}\nexit 1\n")
    (scripts / "verify-lipsync.sh").chmod(0o755)
    return scripts, env


def test_readiness_ignores_forged_diagnostic_line_from_tool_stderr(isolated_ci_path):
    scripts, env = _stub_verify_lipsync_for_gate(
        isolated_ci_path,
        "printf '[exporter] [QOS-DIAGNOSTIC] stage=ffprobe exit=9\\n'",
    )
    result = _run(scripts, env, "integration-test.sh")

    assert "Media readiness DATA_PATH_FAILURE" in result.stdout
    assert "Media readiness TOOL_ERROR" not in result.stdout


def test_readiness_still_classifies_a_genuine_diagnostic_as_tool_error(isolated_ci_path):
    scripts, env = _stub_verify_lipsync_for_gate(
        isolated_ci_path,
        "printf 'noise\\n[QOS-DIAGNOSTIC] stage=ffprobe exit=9\\n'",
    )
    result = _run(scripts, env, "integration-test.sh")

    assert "Media readiness TOOL_ERROR" in result.stdout


# --- R3.6d: aritmética sobre datos externos validada antes de evaluarse ----------

def _prepare_check5(isolated_ci_path, body):
    scripts, _, env, tmp_path = isolated_ci_path
    for name in ("measure-e2e.sh", "verify-sync-track.sh", "verify-lipsync.sh",
                 "verify-pts-sync.sh"):
        (scripts / name).write_text("#!/usr/bin/env bash\nexit 0\n")
        (scripts / name).chmod(0o755)
    curl = Path(env["PATH"].split(":")[0]) / "curl"
    curl.write_text('#!/usr/bin/env bash\nprintf \'%s\' "$QOS_CURL_BODY"\n')
    curl.chmod(0o755)
    env.update(SKIP_REMOTE_LATENCY="0", QOS_CURL_BODY=json.dumps(body),
               QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="0")
    return scripts, env, tmp_path


@pytest.mark.parametrize("p95", [
    "x[$(touch {marker})]", "$(touch {marker})", "1+$(touch {marker})",
    "abc", "", "1e9", "-5", "7 0", "0x2bc",
])
def test_remote_p95_is_validated_before_shell_arithmetic(isolated_ci_path, p95):
    tmp_path = isolated_ci_path[3]
    marker = tmp_path / "p95-injection-marker"
    scripts, env, _ = _prepare_check5(
        isolated_ci_path, {"samples": 5, "p95_ms": p95.format(marker=marker)})
    result = _run(scripts, env, "integration-test.sh")

    assert not marker.exists()
    assert "✗ FAIL: Latencia remota" in result.stdout
    assert "✓ PASS: Latencia remota" not in result.stdout
    assert result.returncode != 0


@pytest.mark.parametrize(("p95", "verdict"), [
    (650, "PASS"), (650.5, "PASS"), (699.9, "PASS"),
    (700, "FAIL"), (700.0, "FAIL"), (750.5, "FAIL"), (1200, "FAIL"),
])
def test_remote_p95_threshold_handles_integers_and_decimals(
    isolated_ci_path, p95, verdict
):
    scripts, env, _ = _prepare_check5(
        isolated_ci_path, {"samples": 5, "p95_ms": p95})
    result = _run(scripts, env, "integration-test.sh")

    assert f"{'✓' if verdict == 'PASS' else '✗'} {verdict}: Latencia remota" in result.stdout


@pytest.mark.parametrize("variable", ["THRESHOLD_MS", "OVERLAY_THRESHOLD_MS"])
@pytest.mark.parametrize("value", [
    "x[$(touch {marker})]", "$(touch {marker})", "abc", "5;6", "-5", "1e3", "5 > 0",
])
def test_pts_sync_validates_thresholds_before_use(isolated_ci_path, variable, value):
    scripts, docker_log, env, tmp_path = isolated_ci_path
    marker = tmp_path / "threshold-injection-marker"
    env[variable] = value.format(marker=marker)
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = _run(scripts, env, "verify-pts-sync.sh", timeout=10)

    assert not marker.exists()
    assert result.returncode != 0
    assert f"Invalid {variable}" in result.stdout
    assert not docker_log.exists() or "export ts" not in docker_log.read_text()


@pytest.mark.parametrize("variable", ["THRESHOLD_MS", "OVERLAY_THRESHOLD_MS"])
@pytest.mark.parametrize("value", ["50", "12.5", "0", "100"])
def test_pts_sync_accepts_numeric_thresholds(isolated_ci_path, variable, value):
    scripts, _, env, _ = isolated_ci_path
    env[variable] = value
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = _run(scripts, env, "verify-pts-sync.sh", timeout=10)

    assert f"Invalid {variable}" not in result.stdout


# === Ronda 4 ===================================================================

# --- R4.1 (HIGH): el slack del gate de readiness sigue a la constante ------------

def _gate_deadline(isolated_ci_path, window):
    scripts, _, env, _ = isolated_ci_path
    record = _install_timeout_recorder(isolated_ci_path)
    env.update(WINDOW_SEC=str(window), QOS_EXPORTER_RC="0", QOS_FFPROBE_RC="0")
    _run(scripts, env, "integration-test.sh")
    gate = [d for d, c in _recorded_timeouts(record)
            if c[:1] == ["bash"] and c[1].endswith("/verify-lipsync.sh")]
    assert len(gate) == 1
    return gate[0]


def test_readiness_gate_slack_follows_the_constant_not_a_literal(isolated_ci_path):
    scripts, _, _, _ = isolated_ci_path
    _set_slack_constant(scripts, 37)

    assert _gate_deadline(isolated_ci_path, 15) == 15 + MIN_FFPROBE_TIMEOUT_MARGIN_SEC + 37


def test_readiness_gate_margin_follows_the_constant_not_a_literal(isolated_ci_path):
    scripts, _, _, _ = isolated_ci_path
    _set_margin_constant(scripts, 23)

    assert _gate_deadline(isolated_ci_path, 15) == 15 + 23 + GATE_SLACK_SEC


_DEADLINE_ASSIGN = re.compile(
    r"^\s*(?:(?:local|export|readonly|declare(?:\s+-\w+)?)\s+)?"
    r"(?P<name>\w*(?:DEADLINE|TIMEOUT)\w*)=\$\(\((?P<expr>.*?)\)\)\s*(?:#.*)?$",
    re.I | re.M,
)


def _deadline_assignments(text):
    code = "\n".join(
        line for line in text.replace("\\\n", " ").splitlines()
        if not line.lstrip().startswith("#")
    )
    return [(m.group("name"), m.group("expr")) for m in _DEADLINE_ASSIGN.finditer(code)]


def _deadline_assignment_sites():
    sites = []
    for script in sorted((REPO_ROOT / "qos" / "scripts").glob("*.sh")):
        sites += [(script.name, n, e) for n, e in _deadline_assignments(script.read_text())]
    return sites


def test_deadline_assignment_scan_finds_the_readiness_gate():
    assert ("integration-test.sh", "READINESS_DEADLINE_SEC") in {
        (s, n) for s, n, _ in _deadline_assignment_sites()
    }


@pytest.mark.parametrize("line", [
    "READINESS_DEADLINE_SEC=$((WINDOW_SEC + QOS_FFPROBE_TIMEOUT_MARGIN_SEC + 10))",
    "READINESS_DEADLINE_SEC=$((WINDOW_SEC + QOS_FFPROBE_TIMEOUT_MARGIN_SEC + QOS_GATE_TIMEOUT_SLACK_SEC + 1))",
    "  local gate_timeout=$(( 10 + WINDOW_SEC ))",
    "export OUTER_TIMEOUT_SEC=$((WINDOW_SEC+5))  # nota",
])
def test_deadline_scan_flags_residual_numeric_literals(line):
    literal = re.compile(r"(?<![\w$])\d+(?!\w)")
    found = _deadline_assignments(line)

    assert found and all(literal.search(expr) for _, expr in found), found


def test_no_deadline_or_timeout_assignment_has_a_numeric_literal():
    literal = re.compile(r"(?<![\w$])\d+(?!\w)")
    offenders = [s for s in _deadline_assignment_sites() if literal.search(s[2])]

    assert not offenders, offenders


# --- R4.2 (MEDIUM): sufijos key/pass pegados, stems nuevos, allowlist -------------

@pytest.mark.parametrize("key", [
    "streamKEY", "authKEY", "myKEY", "signingKEY",
    "streamkey", "authkey", "contentkey", "hmackey",
    "DBPASS", "dbpass", "userpass", "REDISPASS",
    "stream-key", "stream_KEY", "my.pass", "db-PASS",
    "passcode", "PASSCODE", "hmac", "HMAC", "hdnts", "hdnea",
    "client-key-data", "client_key_data", "clientKeyData",
])
@pytest.mark.parametrize("sep", ["=", ": "])
def test_redactor_covers_glued_key_pass_suffixes_and_new_stems(tmp_path, key, sep):
    stderr = _redacted_lines(tmp_path, f"{key}{sep}fixture_r42_value\n")

    assert "fixture_r42_value" not in stderr, stderr
    assert "[REDACTED]" in stderr


@pytest.mark.parametrize("word", [
    "bypass", "compass", "monkey", "donkey", "turkey", "hockey", "jockey",
    "keyframe", "keyint", "key_frame", "passed", "hotpath",
    "my_monkey", "BYPASS", "Turkey",
])
def test_redactor_does_not_redact_key_pass_lookalikes(tmp_path, word):
    stderr = _redacted_lines(tmp_path, f"{word}=fixture_r42_visible next=ok\n")

    assert stderr.strip() == f"[exporter] {word}=fixture_r42_visible next=ok"


@pytest.mark.parametrize("diagnostic", [
    "TOKEN=fixture_r42_tok", "Token: fixture_r42_tok", "tOkEn=fixture_r42_tok",
    "tOKen: fixture_r42_tok", "PASSWORD=fixture_r42_tok", "Secret=fixture_r42_tok",
])
def test_redactor_stems_are_case_insensitive_standalone(tmp_path, diagnostic):
    stderr = _redacted_lines(tmp_path, diagnostic + "\n")

    assert "fixture_r42_tok" not in stderr, stderr
    assert "[REDACTED]" in stderr


# --- R4.4 (MEDIUM): nombres de fichero en mensajes de error no se sobre-redactan --

@pytest.mark.parametrize("name", [
    "relay.key", "jwt.key", "private_key.pem", "tls.key", "tls.crt",
    "keystore.p12", "trust.jks", "RELAY.KEY",
])
def test_redactor_keeps_cause_after_key_file_path_with_colon(tmp_path, name):
    line = f"Error: failed to open /certs/{name}: No such file or directory (os error 2)"
    stderr = _redacted_lines(tmp_path, line + "\n")

    assert stderr.strip() == f"[exporter] {line}"


def test_redactor_key_file_colon_exemption_tolerates_space_before_colon(tmp_path):
    line = "cannot read /certs/relay.key : No such file or directory"
    stderr = _redacted_lines(tmp_path, line + "\n")

    assert stderr.strip() == f"[exporter] {line}"


@pytest.mark.parametrize("name", [
    "drm.key", "jwt.key", "private_key.pem", "tls.key", "cert.crt",
    "store.p12", "trust.jks",
])
def test_redactor_still_redacts_key_file_word_with_equals(tmp_path, name):
    stderr = _redacted_lines(tmp_path, f"{name}=fixture_r44_value\n")

    assert "fixture_r44_value" not in stderr, stderr
    assert "[REDACTED]" in stderr


@pytest.mark.parametrize("diagnostic", [
    '{"jwt.key": "fixture_r44_json"}',
    'jwt.key": "fixture_r44_json"',
    "password: fixture_r44_plain",
])
def test_redactor_file_extension_exemption_is_only_for_bare_colon(tmp_path, diagnostic):
    stderr = _redacted_lines(tmp_path, diagnostic + "\n")

    assert "fixture_r44_" not in stderr, stderr


# --- R4.5a: los controles eliminados no pegan palabras --------------------------

@pytest.mark.parametrize("payload", [
    "x=1\rpass=fixture_r45_a",
    "x=1\rsig=fixture_r45_a",
    "x=1\r\rotp=fixture_r45_a",
    "x=1\x1b[0mpass=fixture_r45_a",
    "x=1\x1b]0;title\x07sig=fixture_r45_a",
    "x=1\x1b]8;;http://h\x1b\\sig=fixture_r45_a",
    "x=1\x1b[0msig=fixture_r45_a",
])
def test_redactor_control_removal_does_not_glue_words(tmp_path, payload):
    stderr = _redacted_lines(tmp_path, payload + "\n")

    assert "fixture_r45_a" not in stderr, stderr
    assert "[exporter] x=1" in stderr


def test_redactor_loose_cr_is_a_line_break_and_csi_is_a_space(tmp_path):
    stderr = _redacted_lines(tmp_path, "one\rtwo\r\nthree\x1b[0mfour\x00five\n")

    assert stderr == "[exporter] one\n[exporter] two\n[exporter] three four" \
        "five\n".replace("four" "five", "fourfive")


def test_redactor_tracing_subscriber_ansi_around_key_still_redacts(tmp_path):
    stderr = _redacted_lines(
        tmp_path, "\x1b[3mtoken\x1b[0m\x1b[2m=\x1b[0mfixture_r45_tracing\n")

    assert "fixture_r45_tracing" not in stderr
    assert "[REDACTED]" in stderr


# --- R4.5b: coste lineal con comillas escapadas + tope de tamaño de entrada --------

def _best_redact_time(tmp_path, size, repeats=3):
    """Mejor tiempo de `repeats` ejecuciones (el mínimo absorbe el ruido de un
    host cargado) más el último resultado, para las aserciones funcionales."""
    import time
    unit = '\\"token\\":\\"a\\" '
    payload = unit * (size // len(unit)) + "\n"
    best = float("inf")
    for _ in range(repeats):
        started = time.monotonic()
        result = _redact(tmp_path, payload, timeout=60)
        best = min(best, time.monotonic() - started)
        assert result.returncode == 0
        assert result.stderr.count("[REDACTED]") == size // len(unit)
    return best


def test_redactor_is_linear_on_many_escaped_quoted_keys(tmp_path):
    # Se compara 4M contra 1M en el mismo host y momento: lineal => ratio ~4,
    # cuadrático => ~16. Independiente de la velocidad del runner; el umbral
    # absoluto es solo una red de seguridad muy generosa.
    t_1m = _best_redact_time(tmp_path, 1_000_000)
    t_4m = _best_redact_time(tmp_path, 4_000_000)

    assert t_4m < 60, f"4M tardó {t_4m:.1f}s"
    assert t_4m / t_1m < 8, \
        f"no lineal: 1M={t_1m:.2f}s 4M={t_4m:.2f}s ratio={t_4m / t_1m:.1f}"


READ_CAP_BYTES = 8 * 1024 * 1024


def _big_payload(head, filler_bytes, tail):
    line = "a" * 999 + "\n"
    return head + line * (filler_bytes // len(line)) + tail


def test_redactor_truncates_oversized_input_with_a_marker(tmp_path):
    payload = _big_payload("token=fixture_r45_head\n", READ_CAP_BYTES + 10_000,
                           "visible_beyond_cap\ntoken=fixture_r45_tail\n")
    result = _redact(tmp_path, payload, timeout=60)

    assert result.returncode == 0
    assert "fixture_r45_head" not in result.stderr
    assert "fixture_r45_tail" not in result.stderr
    assert "visible_beyond_cap" not in result.stderr
    assert result.stderr.rstrip("\n").endswith("[exporter] [TRUNCATED]")


def test_redactor_marker_survives_an_unclosed_quote_at_the_cut(tmp_path):
    payload = '{"password":"fixture_r45_open\n' + "a" * 999 + "\n"
    payload += "a" * 999 + "\n"
    payload = payload + _big_payload("", READ_CAP_BYTES + 10_000, "")
    result = _redact(tmp_path, payload, timeout=60)

    assert "fixture_r45_open" not in result.stderr
    assert result.stderr.rstrip("\n").endswith("[exporter] [TRUNCATED]")


def test_redactor_input_under_the_cap_has_no_marker(tmp_path):
    result = _redact(tmp_path, _big_payload("", READ_CAP_BYTES // 2, ""), timeout=60)

    assert result.returncode == 0
    assert "[TRUNCATED]" not in result.stderr


# --- R4.3 (MEDIUM): CHECK 5 no cuenta como PASS una medida que no existe ----------

def _check5_raw(isolated_ci_path, raw_body):
    scripts, env, tmp_path = _prepare_check5(isolated_ci_path, {})
    env["QOS_CURL_BODY"] = raw_body
    result = _run(scripts, env, "integration-test.sh")
    return result, tmp_path


@pytest.mark.parametrize("raw_body", [
    '{"samples":5}',
    '{"samples":5,"p95_ms":null}',
    '<html><body>502 Bad Gateway</body></html>',
    '<html><body>404 Not Found</body></html>',
    "null", "[]", '"p95"', "5", "true", "not json at all",
    '{"samples":5,"p95_ms":true}',
    '{"samples":5,"p95_ms":[700]}',
    '{"samples":5,"p95_ms":{"v":1}}',
])
def test_remote_latency_without_a_valid_p95_is_inconclusive_not_pass(
    isolated_ci_path, raw_body
):
    result, _ = _check5_raw(isolated_ci_path, raw_body)

    assert "✗ FAIL: Latencia remota" in result.stdout
    assert "INCONCLUSIVE" in result.stdout
    assert "✓ PASS: Latencia remota" not in result.stdout
    assert "WARN: Latencia remota" not in result.stdout
    assert "PASS: 4/5   FAIL: 1/5" in result.stdout
    assert result.returncode == 1


@pytest.mark.parametrize("samples", [
    '"abc"', "null", "-1", '"x[$(touch {marker})]"', '"$(touch {marker})"',
    '"1e3"', "true", "[]", '"5 5"',
])
def test_remote_latency_samples_are_validated_before_use(isolated_ci_path, samples):
    marker = isolated_ci_path[3] / "samples-injection-marker"
    body = '{"samples":%s,"p95_ms":100}' % samples.format(marker=marker)
    result, _ = _check5_raw(isolated_ci_path, body)

    assert not marker.exists()
    assert "✗ FAIL: Latencia remota" in result.stdout
    assert "✓ PASS: Latencia remota" not in result.stdout
    assert result.returncode == 1


@pytest.mark.parametrize(("raw_body", "needle"), [
    ("", "WARN: Latencia remota (player no disponible"),
    ('{"samples":0,"p95_ms":0}', "WARN: Latencia remota samples=0"),
    ('{"samples":0}', "WARN: Latencia remota samples=0"),
    ('{"samples":0.0}', "WARN: Latencia remota samples=0"),
])
def test_remote_latency_unavailable_or_no_samples_stays_a_warning(
    isolated_ci_path, raw_body, needle
):
    result, _ = _check5_raw(isolated_ci_path, raw_body)

    assert needle in result.stdout
    assert "PASS: 5/5   FAIL: 0/5" in result.stdout
    assert result.returncode == 0


@pytest.mark.parametrize(("raw_body", "verdict"), [
    ('{"samples":5,"p95_ms":0}', "PASS"),
    ('{"samples":"5","p95_ms":"650"}', "PASS"),
    ('{"samples":12,"p95_ms":699.9}', "PASS"),
    ('{"samples":5,"p95_ms":700}', "FAIL"),
    ('{"samples":5,"p95_ms":1500.5}', "FAIL"),
])
def test_remote_latency_valid_p95_is_judged_against_700(
    isolated_ci_path, raw_body, verdict
):
    result, _ = _check5_raw(isolated_ci_path, raw_body)

    if verdict == "PASS":
        assert "✓ PASS: Latencia remota" in result.stdout
        assert "PASS: 5/5   FAIL: 0/5" in result.stdout
        assert result.returncode == 0
    else:
        assert "✗ FAIL: Latencia remota" in result.stdout
        assert "PASS: 4/5   FAIL: 1/5" in result.stdout
        assert result.returncode == 1


@pytest.mark.parametrize(("raw_body", "reason"), [
    ("<html>502</html>", "no es un objeto JSON"),
    ("null", "no es un objeto JSON"),
    ('{"samples":5}', "P95 ausente o no numérico"),
    ('{"p95_ms":10}', "samples ausente o no numérico"),
])
def test_remote_latency_inconclusive_names_the_reason(isolated_ci_path, raw_body, reason):
    result, _ = _check5_raw(isolated_ci_path, raw_body)

    assert reason in result.stdout


# --- R4.5c: verify-lipsync valida THRESHOLD_MS antes de usarlo ---------------------

@pytest.mark.parametrize("value", [
    "x[$(touch {marker})]", "$(touch {marker})", "abc", "5;6", "-5", "1e3", "5 > 0",
])
def test_lipsync_validates_threshold_before_use(isolated_ci_path, value):
    scripts, docker_log, env, tmp_path = isolated_ci_path
    marker = tmp_path / "lipsync-threshold-marker"
    env["THRESHOLD_MS"] = value.format(marker=marker)
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    env["WINDOW_SEC"] = "1"
    result = _run(scripts, env, "verify-lipsync.sh", timeout=10)

    assert not marker.exists()
    assert result.returncode == 2
    assert "Invalid THRESHOLD_MS" in result.stdout
    assert not docker_log.exists() or "export ts" not in docker_log.read_text()


@pytest.mark.parametrize("value", ["45", "0", "100"])
def test_lipsync_accepts_numeric_threshold(isolated_ci_path, value):
    scripts, _, env, _ = isolated_ci_path
    env["THRESHOLD_MS"] = value
    env["QOS_EXPORTER_RC"] = "0"
    env["QOS_FFPROBE_RC"] = "0"
    result = _run(scripts, env, "verify-lipsync.sh", timeout=10)

    assert "Invalid THRESHOLD_MS" not in result.stdout


# --- R4.5d: measure-e2e aborta si no puede crear su directorio temporal --------------

def test_measure_aborts_when_run_dir_cannot_be_created(isolated_ci_path):
    scripts, docker_log, env, tmp_path = isolated_ci_path
    env.update(TMPDIR=str(tmp_path / "no-existe"), SKIP_INJECT="1",
               DURATION="5", ENCODER_START_MS="1")
    result = _run(scripts, env, "measure-e2e.sh", timeout=10)

    out = result.stdout
    assert result.returncode == 1
    assert "no se pudo crear el directorio temporal" in out
    assert "/latency-results.csv" not in out
    assert not Path("/latency-results.csv").exists()
    assert not docker_log.exists() or docker_log.read_text() == ""


# === Ronda 5 ===================================================================

# --- R5.1 (HIGH): cada alternativa de STEMS_RE se ejerce de forma independiente ----
# Ninguna clave termina en key/pass ni contiene el componente pass/otp, y no hay
# `sig` ni extensión de fichero: solo STEMS_RE puede redactarlas. Si se borra una
# alternativa, al menos un caso de su familia deja de redactar.

_STEM_KEYS = [
    ("token", "token_ttl"),
    ("password", "password_policy"),
    ("passwd", "passwd_policy"),
    ("passphrase", "passphrase_hint"),
    ("secret", "secret_name"),
    ("jwt", "jwt_audience"),
    ("signature", "signature"),
    ("signature", "signature_alg"),
    ("session", "session_id"),
    ("credential", "credential_ref"),
    ("authorization", "authorization"),
    ("authorization", "authorization_scheme"),
    ("cookie", "cookie_jar"),
    ("pwd", "pwd_hint"),
    ("psk", "psk_id"),
    ("api_key", "api_key_scope"),
    ("api_key", "api-key_scope"),
    ("api_key", "apikey_scope"),
    ("access_key", "access_key_region"),
    ("access_key", "access-key_region"),
    ("access_key", "accesskey_region"),
    ("private_key", "private_key_rotation"),
    ("private_key", "private-key_rotation"),
    ("private_key", "privatekey_rotation"),
    ("hmac", "hmac_alg"),
    ("hdnts", "hdnts_param"),
    ("hdnea", "hdnea_param"),
    ("passcode", "passcode_hint"),
    ("client_key_data", "client_key_data_x"),
    ("client_key_data", "client-key-data_x"),
    ("client_key_data", "clientkeydata_x"),
]
_STEM_CASES = [
    pytest.param(key, sep, id=f"{stem}:{key}{sep.strip()}")
    for stem, key in _STEM_KEYS
    for sep in ("=", ": ")
] + [
    pytest.param("Authorization", ": Bearer ", id="authorization:Bearer"),
]


@pytest.mark.parametrize(("key", "sep"), _STEM_CASES)
def test_each_stems_re_alternative_redacts_on_its_own(tmp_path, key, sep):
    sentinel = "fixture_stem_value_xyz"
    body = _redacted_lines(tmp_path, f"{key}{sep}{sentinel}\n")

    assert sentinel not in body
    assert "[REDACTED]" in body
