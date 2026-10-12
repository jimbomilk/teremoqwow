"""
Punto 3 (despliegue/estructura) — Dockerfile target api, rutas y ausencia de Docker.

Run: python3 -m pytest admin/test_pipeline_deploy.py -q
"""
from __future__ import annotations

import ast
import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import test_pipeline_support as S

ADMIN = S.HERE
DOCKERFILE = ADMIN / "Dockerfile"


def api_stage_lines() -> list[str]:
    text = DOCKERFILE.read_text()
    stage = re.split(r"(?im)^FROM .* AS ", text)
    # trozo que sigue a "FROM ... AS api" hasta el siguiente FROM
    m = re.search(r"(?ims)^FROM [^\n]* AS api\n(.*?)(?=^FROM |\Z)", text)
    assert m, "no se encontró el target api"
    return [l.strip() for l in m.group(1).splitlines() if l.strip() and not l.strip().startswith("#")]


def simulate_copy(dest_root: Path, only_admin_server: bool = False) -> list[str]:
    """Reproduce los `COPY api/... destino` del target api en un directorio temporal (= /app)."""
    copied = []
    for line in api_stage_lines():
        m = re.match(r"COPY\s+(?!--)(\S+)\s+(\S+)$", line)
        if not m:
            continue
        src, dst = m.groups()
        if not src.startswith("api/"):
            continue
        for f in sorted(glob.glob(str(ADMIN / src))):
            name = Path(f).name
            if only_admin_server and name != "admin_server.py":
                continue
            target = dest_root / (name if dst.endswith("/") or dst in (".", "./") else Path(dst).name)
            shutil.copy(f, target)
            copied.append(target.name)
    return copied


def run_import(cwd: Path, modules: str) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "REDIS_URL")}
    return subprocess.run([sys.executable, "-c", modules], cwd=str(cwd), env=env,
                          capture_output=True, text=True, timeout=120)


def test_dockerfile_copies_every_pipeline_module_by_glob():
    lines = api_stage_lines()
    assert "COPY api/pipeline_*.py ./" in lines
    on_disk = {p.name for p in (ADMIN / "api").glob("pipeline_*.py")}
    copied = set()
    for l in lines:
        m = re.match(r"COPY\s+(\S+)\s+\S+$", l)
        if m and m.group(1).startswith("api/"):
            copied |= {Path(f).name for f in glob.glob(str(ADMIN / m.group(1)))}
    assert on_disk and on_disk <= copied
    assert {"pipeline_state.py", "pipeline_api.py", "pipeline_ingest.py"} <= on_disk


def test_import_admin_server_works_with_only_what_dockerfile_copies(tmp_path):
    copied = simulate_copy(tmp_path)
    assert "admin_server.py" in copied and "pipeline_api.py" in copied
    assert sorted(p.name for p in tmp_path.iterdir()) == sorted(copied)  # nada más (ni repo, ni schemas)
    p = run_import(tmp_path, "import admin_server, pipeline_api, pipeline_state, pipeline_ingest; "
                             "assert any(r.rule=='/admin/pipeline/status' for r in admin_server.app.url_map.iter_rules())")
    assert p.returncode == 0, p.stderr[-1500:]


def test_the_import_check_can_fail_when_modules_are_not_copied(tmp_path):
    """Mutante: si el COPY solo llevara admin_server.py, el import debe romper (si no, el test no vale)."""
    simulate_copy(tmp_path, only_admin_server=True)
    assert [p.name for p in tmp_path.iterdir()] == ["admin_server.py"]
    p = run_import(tmp_path, "import admin_server")
    assert p.returncode != 0 and "pipeline_api" in p.stderr


def test_cli_runs_as_script_from_the_copied_layout(tmp_path):
    simulate_copy(tmp_path)
    p = subprocess.run([sys.executable, "pipeline_ingest.py"], cwd=str(tmp_path), input="",
                       capture_output=True, text=True, timeout=60,
                       env={k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "REDIS_URL")})
    assert p.returncode == 2  # arranca (importa pipeline_state) y falla limpiamente por falta de Redis


def test_runtime_image_does_not_install_test_only_packages():
    pip = "\n".join(api_stage_lines())
    for pkg in ("jsonschema", "referencing", "fakeredis", "pytest"):
        assert pkg not in pip


# ── Rutas ─────────────────────────────────────────────────────────────────────

def _rules():
    import admin_server
    return [r for r in admin_server.app.url_map.iter_rules() if "pipeline" in r.rule]


def test_exact_pipeline_routes_and_methods():
    got: dict = {}
    for r in _rules():
        got[r.rule] = got.get(r.rule, frozenset()) | frozenset(r.methods - {"HEAD", "OPTIONS"})
    assert got == {
        "/admin/pipeline/status": frozenset({"GET"}),
        "/admin/pipeline/history": frozenset({"GET"}),
        "/admin/pipeline/phases/<phase>/verification": frozenset({"POST", "DELETE"}),
    }


def test_no_http_route_writes_observations():
    import admin_server
    for r in admin_server.app.url_map.iter_rules():
        writes = r.methods & {"POST", "PUT", "PATCH", "DELETE"}
        low = r.rule.lower()
        if writes:
            assert not any(w in low for w in ("observ", "signal", "ingest")), r.rule
            if "pipeline" in low:
                assert r.rule == "/admin/pipeline/phases/<phase>/verification", r.rule
    # y los verbos de escritura sobre las rutas de lectura se rechazan
    c = S.make_client(pytest.MonkeyPatch(), None)
    for url in ("/admin/pipeline/status", "/admin/pipeline/history", "/admin/pipeline/observations",
                "/admin/pipeline/signals/ingest.video"):
        for m in ("post", "put", "patch", "delete"):
            assert getattr(c, m)(url, headers=S.auth("admin"), json={}).status_code in (404, 405), (m, url)


def test_admin_server_keeps_pipeline_routes_out_of_its_own_source():
    src = (S.API_DIR / "admin_server.py").read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for d in node.decorator_list:
                assert "pipeline" not in ast.unparse(d), f"ruta pipeline definida en admin_server: {node.name}"
            assert not node.name.startswith(("_pipeline", "pipeline_"))
    # lo que queda en admin_server para pipeline es el registro del blueprint (pocas líneas)
    block = src.split("MÓDULO: Pipeline Status", 1)[1].split('if __name__ == "__main__"', 1)[0]
    assert len(block.splitlines()) < 20


# ── Sin Docker ni subprocess en los módulos pipeline_* ────────────────────────

@pytest.mark.parametrize("path", sorted((S.API_DIR).glob("pipeline_*.py")), ids=lambda p: p.name)
def test_pipeline_modules_have_no_docker_or_subprocess(path):
    tree = ast.parse(path.read_text())
    forbidden_mods = {"subprocess", "docker", "pexpect", "sh", "shlex"}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            assert not {a.name.split(".")[0] for a in n.names} & forbidden_mods, (path.name, n.lineno)
        if isinstance(n, ast.ImportFrom):
            assert (n.module or "").split(".")[0] not in forbidden_mods, (path.name, n.lineno)
        if isinstance(n, ast.Call):
            f = ast.unparse(n.func)
            assert f not in ("os.system", "os.popen", "os.execv", "os.spawnl", "Popen", "eval", "exec"), (path.name, f)
    assert "docker.sock" not in path.read_text()
