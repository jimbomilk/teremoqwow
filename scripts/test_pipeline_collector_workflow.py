"""Verifica estructuralmente .github/workflows/pipeline-observe.yml (parseando el YAML)."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
WF_PATH = HERE.parent / ".github/workflows/pipeline-observe.yml"
EXPECTED_CMD = ("/opt/teremoqwow/scripts/pipeline-collector.sh | "
                "docker compose -f /opt/teremoqwow/docker-compose.prod.yml "
                "exec -T admin-api python /app/pipeline_ingest.py")


@pytest.fixture(scope="module")
def wf():
    return yaml.safe_load(WF_PATH.read_text())


@pytest.fixture(scope="module")
def job(wf):
    assert len(wf["jobs"]) == 1
    return next(iter(wf["jobs"].values()))


def test_triggers(wf):
    on = wf.get("on", wf.get(True))  # PyYAML parsea `on` como True
    assert set(on) == {"schedule", "workflow_dispatch"}
    assert on["schedule"] == [{"cron": "3-59/10 * * * *"}]


def _expand_cron_minutes(cron_expr: str) -> list[int]:
    """Expande la parte de minutos de un cron a la lista de minutos que dispara.
    
    Soporta: 
      - */N (cada N minutos): 0, N, 2N, ...
      - M-N/K (rango con step): M, M+K, M+2K, ..., hasta N
      - M,N,O (lista): M, N, O
      - * (todos): 0-59
    
    No soporta nombres (mon, tue, etc).
    """
    parts = cron_expr.split()
    if len(parts) < 5:
        raise ValueError(f"Cron incompleto: {cron_expr}")
    
    min_part = parts[0]
    
    if min_part == "*":
        return list(range(60))
    
    minutes = []
    for expr in min_part.split(","):
        if "/" in expr:
            # */10 o 3-59/10
            base, step = expr.split("/")
            step = int(step)
            if base == "*":
                minutes.extend(range(0, 60, step))
            else:
                # M-N/K
                start, end = map(int, base.split("-"))
                minutes.extend(range(start, end + 1, step))
        elif "-" in expr:
            # M-N (sin step, cada minuto)
            start, end = map(int, expr.split("-"))
            minutes.extend(range(start, end + 1))
        else:
            # Minuto único
            minutes.append(int(expr))
    
    return sorted(set(minutes))


def test_schedule_avoids_high_load_minutes(wf):
    """Verifica que el cron NO dispare en minutos de alta carga de GitHub.
    
    GitHub descarta/retrasa crons en minutos redondos: 0,5,10,15,20,25,30,35,40,45,50,55.
    Este test falla si el workflow usa esos minutos.
    """
    on = wf.get("on", wf.get(True))
    assert "schedule" in on, "Falta trigger schedule"
    assert on["schedule"], "schedule está vacío"
    
    cron = on["schedule"][0].get("cron")
    assert cron, "No hay cron en el primer schedule"
    
    # Minutos de alta carga que GitHub tiende a ignorar/retrasar
    high_load_minutes = {0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}
    
    fired_minutes = _expand_cron_minutes(cron)
    
    # Ningún minuto disparado debe estar en high_load_minutes
    bad_minutes = set(fired_minutes) & high_load_minutes
    assert not bad_minutes, (
        f"Cron '{cron}' dispara en minutos de alta carga {sorted(bad_minutes)}. "
        f"GitHub los ignora/retrasa. Minutos seguros: {sorted(set(range(60)) - high_load_minutes)}"
    )


def test_schedule_interval_at_most_10_minutes(wf):
    """Verifica que el intervalo máximo entre disparos sea ≤10 minutos."""
    on = wf.get("on", wf.get(True))
    assert "schedule" in on
    cron = on["schedule"][0].get("cron")
    assert cron
    
    fired_minutes = sorted(_expand_cron_minutes(cron))
    assert fired_minutes, "Cron no dispara en ningún minuto"
    
    # Intervalo máximo es la diferencia máxima entre disparos consecutivos.
    # También consideramos el intervalo de 59->0 (vuelta a la hora siguiente).
    intervals = []
    for i in range(len(fired_minutes) - 1):
        intervals.append(fired_minutes[i+1] - fired_minutes[i])
    # Intervalo de última ejecución a primera del siguiente ciclo
    intervals.append(60 - fired_minutes[-1] + fired_minutes[0])
    
    max_interval = max(intervals)
    assert max_interval <= 10, (
        f"Cron '{cron}' tiene intervalo máximo {max_interval} min (>10). "
        f"Disparos: {fired_minutes}"
    )


def test_permissions_read_only(wf, job):
    assert wf["permissions"] == {"contents": "read"}
    assert "permissions" not in job or job["permissions"] == {"contents": "read"}


def test_concurrency_without_cancel(wf):
    c = wf["concurrency"]
    assert c["group"] and c["cancel-in-progress"] is False


def test_single_job_timeout(job):
    assert isinstance(job["timeout-minutes"], int) and job["timeout-minutes"] <= 8


def test_single_ssh_step_no_checkout(job):
    steps = job["steps"]
    assert len(steps) == 1
    assert not any("checkout" in str(s.get("uses", "")) for s in steps)
    s = steps[0]
    assert s["uses"] == "appleboy/ssh-action@v1.0.3"
    w = s["with"]
    assert w["host"] == "${{ secrets.PROD_HOST }}"
    assert w["username"] == "deploy"
    assert w["key"] == "${{ secrets.PROD_SSH_KEY }}"
    assert w["command_timeout"] == "5m"


def _script(job):
    return job["steps"][0]["with"]["script"]


def test_script_structure(job):
    script = _script(job)
    lines = [l.strip() for l in script.replace("\\\n", " ").splitlines() if l.strip() and not l.strip().startswith("#")]
    assert lines[0] == "set -euo pipefail"
    assert EXPECTED_CMD in " ".join(script.replace("\\\n", " ").split())
    assert "pipefail" in lines[0]
    assert "Stored" in script and "observation" in script  # comprobación de N almacenadas


def test_script_has_no_test_hooks_or_window_vars(job):
    assert "PIPELINE_" not in WF_PATH.read_text()


def _run_script(job, tmp_path, collector_body, ingest_body):
    """Ejecuta el script REAL del workflow con /opt/teremoqwow redirigido a tmp y docker falso."""
    root = tmp_path / "opt"
    (root / "scripts").mkdir(parents=True)
    col = root / "scripts/pipeline-collector.sh"
    col.write_text("#!/bin/bash\n" + collector_body)
    col.chmod(0o755)
    stubs = tmp_path / "bin"
    stubs.mkdir()
    for tool in ("mktemp", "rm", "tee", "grep", "cat"):
        (stubs / tool).symlink_to(shutil.which(tool))
    dk = stubs / "docker"
    dk.write_text("#!/bin/bash\n" + ingest_body)
    dk.chmod(0o755)
    script = _script(job).replace("/opt/teremoqwow", str(root))
    return subprocess.run([shutil.which("bash"), "-c", script], env={"PATH": str(stubs)},
                          capture_output=True, text=True, timeout=30)


NINE = 'for i in 1 2 3 4 5 6 7 8 9; do echo "{}"; done\n'
COUNT = 'n=$(grep -c .); echo "2026 INFO Stored $n observation(s)" >&2\n'


def test_workflow_script_passes_with_nine_stored(job, tmp_path):
    p = _run_script(job, tmp_path, NINE, COUNT)
    assert p.returncode == 0, p.stderr


def test_workflow_script_fails_when_zero_stored(job, tmp_path):
    p = _run_script(job, tmp_path, "exit 0\n", COUNT)
    assert p.returncode != 0


def test_workflow_script_fails_when_less_than_nine_stored(job, tmp_path):
    p = _run_script(job, tmp_path, 'echo "{}"\n', COUNT)
    assert p.returncode != 0


def test_workflow_script_fails_when_collector_fails_even_with_nine_lines(job, tmp_path):
    p = _run_script(job, tmp_path, NINE + "exit 3\n", COUNT)
    assert p.returncode != 0


def test_workflow_script_fails_when_ingest_fails(job, tmp_path):
    p = _run_script(job, tmp_path, NINE, COUNT + "exit 1\n")
    assert p.returncode != 0


def test_workflow_script_fails_when_ingest_silent(job, tmp_path):
    p = _run_script(job, tmp_path, NINE, "cat >/dev/null\n")  # exit 0 sin "Stored"
    assert p.returncode != 0


def test_no_docker_sock_no_secret_echo_no_other_secrets():
    text = WF_PATH.read_text()
    assert "docker.sock" not in text
    import re
    assert sorted(set(re.findall(r"secrets\.(\w+)", text))) == ["PROD_HOST", "PROD_SSH_KEY"]
    assert not re.search(r"\b(echo|printf)\b[^\n]*secrets", text)
    assert "ACTIONS_STEP_DEBUG" not in text
    for s in yaml.safe_load(text)["jobs"].values():
        assert "env" not in s or not s["env"]
        assert all("env" not in st for st in s["steps"])
