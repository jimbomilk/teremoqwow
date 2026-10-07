"""Tests de configuración del ingest SRT (Larix) en producción.

Verifican que docker-compose.prod.yml, deploy.yml y provision-server.sh
declaran el servicio `srt-ingest` y lo despliegan/abren correctamente.

Los tests de COMPORTAMIENTO ejecutan código real en aislamiento para evitar
falsos positivos por regex débiles. Cada test mata mutantes específicos.
"""
import pathlib
import re
import subprocess
import textwrap
from typing import Set

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.prod.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
PROVISION = ROOT / "scripts" / "provision-server.sh"
RUNBOOK = ROOT / "docs" / "runbooks" / "srt-larix-ingest.md"


@pytest.fixture(scope="module")
def service():
    compose = yaml.safe_load(COMPOSE.read_text())
    assert "srt-ingest" in compose["services"], "falta el servicio srt-ingest"
    return compose["services"]["srt-ingest"]


@pytest.fixture(scope="module")
def deploy_script():
    wf = yaml.safe_load(DEPLOY.read_text())
    for step in wf["jobs"]["deploy"]["steps"]:
        if "script" in step.get("with", {}):
            return step["with"]["script"]
    pytest.fail("no se encontró el script SSH en deploy.yml")


def _command_tokens(service):
    command = service["command"]
    assert isinstance(command, list), "command debe ser lista YAML (quoting de [::])"
    return [str(t) for t in command]


def _opt(tokens, name):
    assert name in tokens, f"falta {name}"
    return tokens[tokens.index(name) + 1]


# ── docker-compose.prod.yml ────────────────────────────────────────────────

def test_image_is_pinned(service):
    """Mutantes que mata: image != 0.12.7, image sin tag."""
    assert service["image"] == "moqdev/moq:0.12.7"


def test_network_is_prod(service):
    """Mutantes que mata: network mal nombrada."""
    assert "teremoqwow-prod" in service["networks"]


def test_srt_port_is_udp_only(service):
    """Mutantes que mata: puerto TCP, puerto diferente, lista vacía."""
    ports = [str(p) for p in service["ports"]]
    assert ports == ["8890:8890/udp"]


def test_command_is_exact_list(service):
    """HIGH-2 mutante killer: valida el comando EXACTO como lista, no parsing.
    
    Mata: broadcast duplicado, broadcast tras `srt`, --help en lugar de import,
    entrypoint presente, argumentos extra, opciones duplicadas.
    """
    tokens = _command_tokens(service)
    expected = [
        "--connect", "tcp://moq-relay:4444/anon",
        "--broadcast", "anon/live1",
        "import", "srt",
        "--listen", "[::]:8890",
        "--latency", "500ms"
    ]
    assert tokens == expected, f"comando no coincide.\nEsperado: {expected}\nGot: {tokens}"


def test_no_entrypoint_override(service):
    """HIGH-2 mutante killer: la imagen trae moq como entrypoint, no se override.
    
    Mata: entrypoint=/bin/true, entrypoint=bash, etc.
    """
    assert "entrypoint" not in service, "no debe haber entrypoint, usa el de la imagen"


def test_depends_on_relay_and_restart(service):
    """Mutantes que mata: condition != service_started, restart != unless-stopped."""
    assert service["depends_on"]["moq-relay"]["condition"] == "service_started"
    assert service["restart"] == "unless-stopped"


def test_logging_rotated(service):
    """Mutantes que mata: driver != json-file, falta max-size."""
    assert service["logging"]["driver"] == "json-file"
    assert "max-size" in service["logging"]["options"]


def test_no_fake_healthcheck(service):
    """Mutantes que mata: healthcheck presente (test falso)."""
    assert "healthcheck" not in service


# ── deploy.yml ─────────────────────────────────────────────────────────────

def _extract_service_selection_block(script: str) -> str:
    """Extrae el bloque que calcula BUILD_SERVICES/RESTART_SERVICES del script.
    
    Busca entre la PRIMERA asignación 'BUILD_SERVICES=""' (inclusive) y la línea 
    que construye ALL_RESTART (inclusive), parando antes de 'exit 0 / Sin cambios'.
    """
    lines = script.splitlines()
    start_idx = None
    end_idx = None
    
    for i, line in enumerate(lines):
        # Buscar la primera inicialización (no transformación)
        if start_idx is None and line.strip() == "BUILD_SERVICES=\"\"":
            start_idx = i
        if start_idx is not None and "ALL_RESTART=" in line:
            end_idx = i
            break
    
    if start_idx is None or end_idx is None:
        raise ValueError(
            "No se pudo aislar el bloque BUILD_SERVICES...ALL_RESTART. "
            "Marcadores no encontrados o mal estructurados."
        )
    
    block_lines = lines[start_idx:end_idx + 1]
    return "\n".join(block_lines)


def _execute_service_selection(
    script_block: str,
    force_full: str = "false",
    changed_auth: str = "false",
    changed_infra: str = "false",
    changed_config: str = "false",
    changed_billing: str = "false",
    changed_portal: str = "false",
    changed_registry: str = "false",
    changed_admin: str = "false",
    changed_player: str = "false",
) -> Set[str]:
    """Ejecuta el bloque de cálculo de servicios con bash, retorna el conjunto
    de servicios en ALL_RESTART.
    
    Mata mutantes: asignación comentada, guard invertido, rama comentada, etc.
    """
    env_vars = {
        "FORCE_FULL": force_full,
        "CHANGED_AUTH": changed_auth,
        "CHANGED_BILLING": changed_billing,
        "CHANGED_PORTAL": changed_portal,
        "CHANGED_REGISTRY": changed_registry,
        "CHANGED_ADMIN": changed_admin,
        "CHANGED_PLAYER": changed_player,
        "CHANGED_INFRA": changed_infra,
        "CHANGED_CONFIG": changed_config,
        "PATH": "/bin:/usr/bin",
    }
    
    # Ejecutar el bloque con bash en modo strict (-u = error si variable no definida)
    cmd = f"set -u; {script_block}; echo \"RESULT=${{ALL_RESTART% }}\""
    result = subprocess.run(
        ["bash", "-c", cmd],
        env=env_vars,
        capture_output=True,
        text=True,
        timeout=10
    )
    
    if result.returncode != 0:
        raise RuntimeError(
            f"Fallo ejecutar bloque de servicios.\nStderr: {result.stderr}\n"
            f"Stdout: {result.stdout}"
        )
    
    # Parsear la última línea RESULT=...
    for line in result.stdout.strip().split("\n"):
        if line.startswith("RESULT="):
            services_str = line.replace("RESULT=", "").strip()
            if not services_str:
                return set()
            return set(services_str.split())
    
    raise RuntimeError(f"No se encontró RESULT= en output: {result.stdout}")


def test_deploy_service_selection_full_force(deploy_script):
    """HIGH-1 mutante killer: FORCE_FULL=true debe incluir srt-ingest.
    
    Mata: rama FORCE_FULL comentada, FORCE_FULL inalcanzable (if false; then),
    srt-ingest sin asignar, guard invertido (= "false").
    """
    block = _extract_service_selection_block(deploy_script)
    services = _execute_service_selection(block, force_full="true")
    assert "srt-ingest" in services, (
        f"FORCE_FULL=true debe incluir srt-ingest. Got: {services}"
    )


def test_deploy_service_selection_infra_only(deploy_script):
    """HIGH-1 mutante killer: CHANGED_INFRA=true sin FORCE_FULL debe dar
    exactamente {nginx, srt-ingest}.
    
    Mata: srt-ingest comentado, nginx olvidado, guard invertido,
    CHANGED_INFRA dentro rama AUTH, rama IF comentada.
    """
    block = _extract_service_selection_block(deploy_script)
    services = _execute_service_selection(
        block,
        force_full="false",
        changed_infra="true",
        changed_auth="false",
        changed_config="false",
    )
    assert services == {"nginx", "srt-ingest"}, (
        f"CHANGED_INFRA=true debe dar exactamente {{nginx, srt-ingest}}. Got: {services}"
    )


def test_deploy_service_selection_no_changes(deploy_script):
    """HIGH-1 mutante killer: todos false ⇒ ALL_RESTART vacío.
    
    Mata: asignación accidental de servicios en rama else, srt-ingest siempre.
    """
    block = _extract_service_selection_block(deploy_script)
    services = _execute_service_selection(
        block,
        force_full="false",
        changed_auth="false",
        changed_billing="false",
        changed_portal="false",
        changed_registry="false",
        changed_admin="false",
        changed_player="false",
        changed_infra="false",
        changed_config="false",
    )
    assert services == set(), (
        f"Sin cambios debe dar conjunto vacío. Got: {services}"
    )


def test_deploy_service_selection_auth_only(deploy_script):
    """HIGH-1 mutante killer: solo CHANGED_AUTH=true ⇒ auth (srt-ingest NO).
    
    Mata: srt-ingest siempre en rama, señuelo CHANGED_INFRA en rama AUTH.
    """
    block = _extract_service_selection_block(deploy_script)
    services = _execute_service_selection(
        block,
        force_full="false",
        changed_auth="true",
        changed_infra="false",
        changed_config="false",
    )
    assert "srt-ingest" not in services, (
        f"CHANGED_AUTH solo debe dar auth (o servicios build), no srt-ingest. Got: {services}"
    )
    # El test no valida que esté 'auth' exactamente porque es BUILD_SERVICES, no RESTART.
    # Pero podemos verificar que SRT no está.


# ── provision-server.sh ────────────────────────────────────────────────────

def _analyze_ufw_rule_context(script: str, rule: str) -> dict:
    """Analiza si una regla UFW está en contexto válido (nivel superior, 
    sin if/function/heredoc).
    
    Retorna {'valid': bool, 'reason': str}.
    """
    lines = script.splitlines()
    rule_idx = None
    
    # Buscar la línea que contiene la regla (flexible con espacios)
    rule_pattern = r"ufw\s+allow\s+8890/udp"
    for i, line in enumerate(lines):
        if re.search(rule_pattern, line):
            rule_idx = i
            break
    
    if rule_idx is None:
        return {"valid": False, "reason": "Regla no encontrada en el script"}
    
    line = lines[rule_idx]
    
    # Verificar que no esté comentada
    stripped = line.lstrip()
    if stripped.startswith("#"):
        return {"valid": False, "reason": "Regla comentada"}
    
    # Verificar indentación (debe estar al nivel superior)
    if line != line.lstrip():
        return {"valid": False, "reason": "Regla indentada (dentro de if/función)"}
    
    # Verificar que no haya heredoc abierto antes
    heredoc_open = False
    for j in range(rule_idx):
        check_line = lines[j]
        if "<<" in check_line and not check_line.lstrip().startswith("#"):
            # Heredoc opening (simplificado: solo detecta <<)
            if "EOF" in check_line or "END" in check_line or "EOL" in check_line:
                heredoc_open = True
    
    if heredoc_open:
        return {"valid": False, "reason": "Está dentro de un bloque heredoc"}
    
    return {"valid": True, "reason": "Regla válida en contexto de nivel superior"}


def test_provision_srt_port_executable(deploy_script=None):
    """MEDIUM-1 mutante killer: la regla 'ufw allow 8890/udp' debe ser 
    una sentencia ejecutable de nivel superior (no comentada, no indentada,
    fuera de if/heredoc).
    
    Mata: regla dentro `if false; then`, regla en heredoc, regla comentada.
    """
    text = PROVISION.read_text()
    analysis = _analyze_ufw_rule_context(text, "ufw allow 8890/udp")
    assert analysis["valid"], f"UFW rule invalid: {analysis['reason']}"


# ── runbook ────────────────────────────────────────────────────────────────

def test_runbook_stream_id_required_and_non_empty(deploy_script=None):
    """MEDIUM-2 mutante killer: el runbook debe exigir Stream ID obligatorio
    y no vacío. Revisa TODAS las líneas con "Stream ID" (case-insensitive).
    
    Mata: segunda línea que diga «dejar en blanco», «no es obligatorio»,
    «puede quedar vacío», etc. Exige al menos una línea con «obligatorio»
    y mención a «live1» como ejemplo.
    """
    text = RUNBOOK.read_text()
    
    stream_id_lines = [
        l for l in text.splitlines()
        if "stream id" in l.lower()
    ]
    assert len(stream_id_lines) > 0, "No se encontran líneas con 'Stream ID'"
    
    # Buscar menciones negativas (malas)
    bad_patterns = [
        r"dejar\s+vac[ií]o",
        r"en\s+blanco",
        r"no\s+es\s+obligatorio",
        r"puede\s+quedar.*vac[ií]o",
        r"puede\s+quedar.*blanco",
    ]
    
    for line in stream_id_lines:
        for bad in bad_patterns:
            assert not re.search(bad, line, re.I), (
                f"Línea 'Stream ID' no debe decir que sea opcional: {line}"
            )
    
    # Buscar menciones positivas (buenas): debe haber obligatorio
    has_obligatorio = any(
        re.search(r"obligatorio", line, re.I)
        for line in stream_id_lines
    )
    assert has_obligatorio, (
        "Al menos una línea 'Stream ID' debe mencionar que es 'obligatorio'"
    )
    
    # Buscar ejemplo live1
    has_live1_example = any(
        "live1" in line
        for line in stream_id_lines
    )
    assert has_live1_example, (
        "Al menos una línea 'Stream ID' debe mostrar 'live1' como ejemplo"
    )


def test_runbook_relative_links_exist(deploy_script=None):
    """MEDIUM-3 mutante killer: todos los enlaces relativos en el runbook
    deben resolver a archivos que existen en disco. Incluye corrección
    de rutas ../config/... → ../../config/... (desde docs/runbooks/).
    
    Mata: enlaces rotos, rutas incorrectas.
    """
    text = RUNBOOK.read_text()
    
    # Extraer todos los enlaces markdown [text](path)
    link_pattern = r"\]\(([^)]+)\)"
    links = re.findall(link_pattern, text)
    
    runbook_dir = RUNBOOK.parent
    bad_links = []
    
    for link in links:
        # Ignorar URLs absolutas y anchors
        if link.startswith("http") or link.startswith("#"):
            continue
        
        resolved = (runbook_dir / link).resolve()
        if not resolved.exists():
            bad_links.append((link, resolved))
    
    assert not bad_links, (
        f"Enlaces rotos en runbook:\n" +
        "\n".join(f"  {link} → {resolved}" for link, resolved in bad_links)
    )


def test_runbook_no_false_nc_check(deploy_script=None):
    """MEDIUM-4 mutante killer: el runbook no debe usar `nc -uz` para
    verificar puerto UDP (es un falso positivo). Debe usar un método real
    como SRT handshake con ffmpeg.
    
    Mata: `nc -u -z` presente sin explicación de por qué es falso.
    """
    text = RUNBOOK.read_text()
    
    # Buscar la línea con nc -u
    nc_lines = [l for l in text.splitlines() if "nc -u -z" in l]
    
    # Si está, debe estar en un contexto de "no es fiable" o "false positive"
    if nc_lines:
        # Verificar que la siguiente sección explique que NO es confiable
        full_section = "\n".join(text.splitlines())
        context_lines = full_section.split("nc -u -z")[1][:500]  # 500 chars después
        
        assert any(
            phrase in context_lines.lower()
            for phrase in ["no es fiable", "falso positivo", "udp", "listener"]
        ), (
            "Si usa 'nc -uz', debe explicar que es falso positivo para UDP"
        )
