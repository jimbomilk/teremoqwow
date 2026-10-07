"""Guard: the CI runner has no ffprobe; the QoS scripts call it on the host."""
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "integration-test.yml"


def _steps(workflow_text):
    return yaml.safe_load(workflow_text)["jobs"]["qos-integration"]["steps"]


def _check_ffmpeg_before_qos(steps):
    install = [
        i for i, s in enumerate(steps)
        if "apt-get install" in s.get("run", "") and "ffmpeg" in s.get("run", "")
    ]
    runs = [
        i for i, s in enumerate(steps)
        if "qos/scripts/integration-test.sh" in s.get("run", "")
    ]
    assert install, "qos-integration must install ffmpeg (provides ffprobe)"
    assert runs, "qos-integration must run qos/scripts/integration-test.sh"
    assert install[0] < runs[0], "ffmpeg install must precede the QoS test step"


def test_qos_integration_installs_ffmpeg_before_running_checks():
    _check_ffmpeg_before_qos(_steps(WORKFLOW.read_text()))


def test_install_step_prints_ffprobe_version():
    step = next(s for s in _steps(WORKFLOW.read_text()) if "apt-get install" in s.get("run", ""))
    assert "ffprobe -version" in step["run"]


def test_mutant_install_after_run_is_detected():
    steps = _steps(WORKFLOW.read_text())
    idx = next(i for i, s in enumerate(steps) if "apt-get install" in s.get("run", ""))
    steps.append(steps.pop(idx))
    with pytest.raises(AssertionError):
        _check_ffmpeg_before_qos(steps)


def test_mutant_without_ffmpeg_is_detected():
    steps = _steps(WORKFLOW.read_text().replace("ffmpeg", "curl"))
    with pytest.raises(AssertionError):
        _check_ffmpeg_before_qos(steps)
