"""Guard del workflow CI: tests-python debe preparar Node + deps del player
antes de ejecutar player/test_player_html.py (que lanza `npm run build` y Vite)."""
import copy
from pathlib import Path

import pytest
import yaml

CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
PLAYER_TEST = "player/test_player_html.py"


def _steps(workflow):
    return workflow["jobs"]["tests-python"]["steps"]


def _problems(workflow):
    """Devuelve lista de incumplimientos (vacía = OK)."""
    steps = _steps(workflow)
    idx = {"test": None, "node": None, "install": None}
    for i, s in enumerate(steps):
        if PLAYER_TEST in s.get("run", "") and idx["test"] is None:
            idx["test"] = i
        if s.get("uses", "").startswith("actions/setup-node@") and idx["node"] is None:
            idx["node"] = i
        run = s.get("run", "")
        if "npm" in run and "install" in run and "player" in run and idx["install"] is None:
            idx["install"] = i
    out = []
    if idx["test"] is None:
        return [f"no hay paso que ejecute {PLAYER_TEST}"]
    for name in ("node", "install"):
        if idx[name] is None:
            out.append(f"falta paso {name} en tests-python")
        elif idx[name] > idx["test"]:
            out.append(f"paso {name} va DESPUÉS de {PLAYER_TEST}")
    if idx["node"] is not None and idx["install"] is not None and idx["node"] > idx["install"]:
        out.append("setup-node debe ir antes de la instalación")
    return out


@pytest.fixture(scope="module")
def workflow():
    return yaml.safe_load(CI.read_text())


def test_ci_prepara_node_y_deps_player_antes_de_test_player_html(workflow):
    assert _problems(workflow) == []


def test_mutante_sin_instalacion_falla(workflow):
    wf = copy.deepcopy(workflow)
    wf["jobs"]["tests-python"]["steps"] = [
        s for s in _steps(wf) if "npm" not in s.get("run", "")
    ]
    assert _problems(wf)


def test_mutante_instalacion_despues_falla(workflow):
    wf = copy.deepcopy(workflow)
    steps = _steps(wf)
    i = next(n for n, s in enumerate(steps) if "npm" in s.get("run", ""))
    steps.append(steps.pop(i))
    assert _problems(wf)


def test_mutante_sin_setup_node_falla(workflow):
    wf = copy.deepcopy(workflow)
    wf["jobs"]["tests-python"]["steps"] = [
        s for s in _steps(wf) if not s.get("uses", "").startswith("actions/setup-node@")
    ]
    assert _problems(wf)
