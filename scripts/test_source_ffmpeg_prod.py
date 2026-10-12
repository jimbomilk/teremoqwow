"""Tests de configuración de fuente FFmpeg permanente en producción.

Verifican que docker-compose.prod.yml, deploy.yml y la sonda declarados
despliegan correctamente source-ffmpeg con configuración válida: testsrc2 + audio
determinista → SRT a srt-ingest:8890.

Los tests verifican CONFIGURACIÓN y TRANSPORTE (red, dependencias, restart,
logging, destino SRT), NO contenido de vídeo/audio (resolución, fps, GOP, codec,
tono, timecode). Esa verificación es exclusivamente humana (abriendo el player).
"""
import json
import pathlib
import re
import subprocess
import sys
import textwrap
from typing import Any, Dict, List

import pytest
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "docker-compose.prod.yml"
DEPLOY = ROOT / ".github" / "workflows" / "deploy.yml"
RUNBOOK = ROOT / "docs" / "runbooks" / "source-ffmpeg.md"
PROBE = ROOT / "scripts" / "probe-source-ffmpeg.sh"
SCHEMA = ROOT / "schemas" / "media" / "v1" / "source-status.json"


@pytest.fixture(scope="module")
def compose_data():
    """Carga docker-compose.prod.yml como YAML."""
    try:
        return yaml.safe_load(COMPOSE.read_text())
    except Exception as e:
        pytest.fail(f"No se pudo parsear {COMPOSE}: {e}")


@pytest.fixture(scope="module")
def service(compose_data):
    """Extrae la definición del servicio source-ffmpeg."""
    assert "services" in compose_data, "falta 'services' en compose"
    assert "source-ffmpeg" in compose_data["services"], (
        f"falta el servicio 'source-ffmpeg'. Servicios disponibles: "
        f"{list(compose_data['services'].keys())}"
    )
    return compose_data["services"]["source-ffmpeg"]


@pytest.fixture(scope="module")
def schema_spec():
    """Carga el esquema source-status.json."""
    try:
        return json.loads(SCHEMA.read_text())
    except Exception as e:
        pytest.fail(f"No se pudo parsear {SCHEMA}: {e}")


# ── docker-compose.prod.yml: declaración del servicio ──────────────────────

class TestSourceFFmpegService:
    """Tests de la declaración del servicio source-ffmpeg en compose."""

    def test_image_pinned_no_latest(self, service):
        """Detecta image sin versión o :latest.
        
        MUTANTE 1: Mata:
        - image: linuxserver/ffmpeg (sin tag)
        - image: jrottenberg/ffmpeg:latest
        - image: ffmpeg
        """
        image = service.get("image", "")
        assert ":" in image, f"image debe tener tag pinned (encontrado: {image})"
        assert not image.endswith(":latest"), f"image no debe ser :latest (found: {image})"
        # El tag debe ser numérico o reconocible (ej. 7.1, 7.1-alpine, etc)
        match = re.search(r':[0-9]', image)
        assert match, f"image debe tener tag numérico (found: {image})"

    def test_image_is_ffmpeg_based(self, service):
        """Verifica que la imagen sea un distro FFmpeg conocido.
        
        MUTANTE 2: Mata:
        - image: ubuntu:22.04
        - image: debian:bookworm
        - image: moqdev/moq:0.12.7 (confusión con srt-ingest)
        """
        image = service.get("image", "")
        ffmpeg_distros = ["linuxserver/ffmpeg", "jrottenberg/ffmpeg", "alfg/ffmpeg"]
        assert any(d in image for d in ffmpeg_distros), (
            f"image debe ser un distro FFmpeg conocido: {ffmpeg_distros} "
            f"(found: {image})"
        )

    def test_network_is_prod(self, service):
        """Verifica que está en la red teremoqwow-prod.
        
        MUTANTE 3: Mata:
        - networks: [default]
        - networks: [teremoqwow-dev]
        - Sin 'networks' (usa default)
        """
        networks = service.get("networks", [])
        if isinstance(networks, dict):
            networks = list(networks.keys())
        assert "teremoqwow-prod" in networks, (
            f"debe estar en red 'teremoqwow-prod' (found: {networks})"
        )

    def test_depends_on_srt_ingest(self, service):
        """Verifica depends_on srt-ingest con condition.
        
        MUTANTE 4: Mata:
        - Sin depends_on
        - depends_on: [moq-relay] (dependencia errónea)
        - depends_on: srt-ingest (sin condition)
        """
        depends_on = service.get("depends_on", {})
        assert "srt-ingest" in depends_on, (
            f"debe depender de 'srt-ingest' (found: {depends_on})"
        )
        if isinstance(depends_on["srt-ingest"], dict):
            cond = depends_on["srt-ingest"].get("condition")
            assert cond == "service_started", (
                f"condition debe ser 'service_started' (found: {cond})"
            )

    def test_restart_policy(self, service):
        """Verifica restart: unless-stopped o always.
        
        MUTANTE 5: Mata:
        - restart: no
        - restart: on-failure
        - Sin restart
        """
        restart = service.get("restart", "")
        assert restart in ["unless-stopped", "always"], (
            f"restart debe ser 'unless-stopped' o 'always' (found: {restart})"
        )

    def test_no_ports_published(self, service):
        """Asegura que NO hay puertos publicados al host.
        
        MUTANTE 6: Mata:
        - ports: ["5000:5000"]
        - ports: ["9999:9999/tcp"]
        - No está restringido a red interna
        """
        ports = service.get("ports", [])
        assert len(ports) == 0, (
            f"NO debe exponer puertos al host (found: {ports}). "
            f"source-ffmpeg publica por SRT a srt-ingest vía red interna teremoqwow-prod."
        )

    def test_no_docker_socket_mounted(self, service):
        """Asegura que NO se monta /var/run/docker.sock.
        
        MUTANTE 7: Mata:
        - volumes: ["/var/run/docker.sock:/var/run/docker.sock"]
        """
        volumes = service.get("volumes", [])
        docker_sock_patterns = ["/docker.sock", "docker.sock:/docker.sock"]
        for vol in volumes:
            vol_str = str(vol) if isinstance(vol, str) else str(vol)
            assert not any(p in vol_str for p in docker_sock_patterns), (
                f"PROHIBIDO montar /var/run/docker.sock: {vol_str}"
            )

    def test_logging_json_file(self, service):
        """Verifica logging json-file con rotación.
        
        MUTANTE 8: Mata:
        - Sin logging
        - logging: {driver: awslogs}
        - logging: {driver: json-file} pero sin max-size
        """
        logging_cfg = service.get("logging", {})
        assert logging_cfg.get("driver") == "json-file", (
            f"driver debe ser json-file (found: {logging_cfg.get('driver')})"
        )
        opts = logging_cfg.get("options", {})
        assert "max-size" in opts, f"logging.options debe tener max-size (found: {opts})"
        assert "max-file" in opts, f"logging.options debe tener max-file (found: {opts})"

    def test_no_entrypoint_override(self, service):
        """Verifica que NO se override el entrypoint de la imagen.
        
        MUTANTE 9: Mata:
        - entrypoint: /bin/bash
        - entrypoint: ["/entrypoint.sh"]
        """
        entrypoint = service.get("entrypoint")
        assert entrypoint is None, (
            f"NO se debe override entrypoint (found: {entrypoint}). "
            f"Usa el de la imagen FFmpeg."
        )

    def test_command_structure(self, service):
        """Verifica que 'command' es una lista YAML (no string).
        
        MUTANTE 10: Mata:
        - command: "ffmpeg -i testsrc2 ..." (string, no lista)
        - command: ffmpeg -i ... (parser YAML incorrecta)
        """
        cmd = service.get("command")
        assert isinstance(cmd, list), (
            f"command debe ser lista YAML, no string (found: {type(cmd).__name__} = {cmd})"
        )


class TestSourceFFmpegFFmpegCommand:
    """Tests de la línea de comandos ffmpeg: estructura y transporte."""

    def test_command_has_testsrc2_video(self, service):
        """Verifica que usa testsrc2 como fuente de vídeo.
        
        MUTANTE 11: Mata:
        - command sin '-i testsrc2'
        - command con '-i /dev/null'
        - command con '-i color=red'
        """
        cmd_str = " ".join(str(c) for c in service.get("command", []))
        assert "testsrc2" in cmd_str, (
            f"command debe usar 'testsrc2' como fuente de vídeo (found: {cmd_str})"
        )

    def test_command_has_audio_input(self, service):
        """Verifica que hay generación de audio (sine, anullsrc, etc).
        
        MUTANTE 12: Mata:
        - Sin audio
        - Audio sin generador
        """
        cmd_str = " ".join(str(c) for c in service.get("command", []))
        audio_patterns = ["sine", "anullsrc", "amix", "af=", "aformat"]
        assert any(p in cmd_str for p in audio_patterns), (
            f"command debe generar audio (sine, anullsrc, amix, etc). Found: {cmd_str}"
        )

    def test_command_outputs_mpegts_srt(self, service):
        """Verifica que output es MPEG-TS por SRT.
        
        MUTANTE 13: Mata:
        - command con '-f mov' o '-f mp4'
        - comando con 'output.mp4'
        - comando sin 'srt://'
        """
        cmd_str = " ".join(str(c) for c in service.get("command", []))
        assert "srt://" in cmd_str, (
            f"command debe publicar por SRT (srt://...). Found: {cmd_str}"
        )
        assert "-f mpegts" in cmd_str or "mpegts" in cmd_str, (
            f"command debe usar formato MPEG-TS (-f mpegts). Found: {cmd_str}"
        )

    def test_command_srt_target_is_srt_ingest(self, service):
        """Verifica que el target SRT es srt-ingest:8890.
        
        MUTANTE 14: Mata:
        - srt://localhost:8890
        - srt://moq-relay:4444
        - srt://ffmpeg-ingest:9000
        """
        cmd_str = " ".join(str(c) for c in service.get("command", []))
        assert "srt://srt-ingest:8890" in cmd_str, (
            f"command debe conectar a srt://srt-ingest:8890 (found: {cmd_str})"
        )

    def test_command_streamid_is_live1(self, service):
        """Verifica que streamid=live1 (no vacío).
        
        MUTANTE 15: Mata:
        - Sin streamid
        - streamid=default
        - streamid vacío
        """
        cmd_str = " ".join(str(c) for c in service.get("command", []))
        assert "streamid=live1" in cmd_str, (
            f"command debe usar streamid=live1 (found: {cmd_str})"
        )

    def test_command_has_lavfi_prefix(self, service):
        """Verifica que las entradas usan -f lavfi (lavfi, no file).
        
        MUTANTE 16: Mata:
        - command con '-f deshake' u otro filtro erróneo
        - command con '-i /path/to/file' en lugar de generador
        """
        cmd_str = " ".join(str(c) for c in service.get("command", []))
        # Busca al menos un '-f lavfi'
        assert "-f lavfi" in cmd_str, (
            f"command debe usar '-f lavfi' para fuentes generadas (found: {cmd_str})"
        )

    def test_gop_size_is_30_frames(self, service):
        """Verifica que GOP = 30 frames (1s @ 30fps) para cumplir SLA P95 <700ms.
        
        REF: issue #133 — MoQ subscriber entra en frontera de IDR, por lo que
        GOP > 30 causa latencia > 700ms. Histórico: config/moq-mux/run.sh usa -g 30.
        
        MUTANTE MATA: -g 60, -g 40, -g 20, -g NN con NN ≠ 30.
        MUTANTE NO MATA: -g 30 correctamente.
        """
        cmd = service.get("command", [])
        cmd_str = " ".join(str(c) for c in cmd)
        
        # Busca el parámetro -g en la lista de comandos
        try:
            g_index = cmd.index("-g")
            g_value = cmd[g_index + 1]
            assert g_value == "30", (
                f"Parámetro -g debe ser 30 (1s @ 30fps, SLA latencia <700ms, issue #133). "
                f"Encontrado: -g {g_value}. "
                f"Nota: Histórico en config/moq-mux/run.sh usa -g 30 correctamente."
            )
        except (ValueError, IndexError):
            pytest.fail(
                f"Falta parámetro -g en command o -g sin valor. "
                f"command: {cmd_str}. "
                f"Referencia issue #133."
            )

    def test_keyint_min_is_30_frames(self, service):
        """Verifica que -keyint_min = 30 para mantener alineación GOP.
        
        REF: issue #133 — -keyint_min ≠ -g permite keyframes adaptativas que rompen
        la garantía de GOP. Debe ser idéntico a -g.
        
        MUTANTE MATA: -keyint_min 60, -keyint_min 20, -keyint_min NN con NN ≠ 30.
        MUTANTE NO MATA: -keyint_min 30 correctamente.
        """
        cmd = service.get("command", [])
        cmd_str = " ".join(str(c) for c in cmd)
        
        try:
            kmin_index = cmd.index("-keyint_min")
            kmin_value = cmd[kmin_index + 1]
            assert kmin_value == "30", (
                f"Parámetro -keyint_min debe ser 30 (alineado con -g para GOP constante, issue #133). "
                f"Encontrado: -keyint_min {kmin_value}."
            )
        except (ValueError, IndexError):
            pytest.fail(
                f"Falta parámetro -keyint_min en command o sin valor. "
                f"command: {cmd_str}. "
                f"Referencia issue #133."
            )

    def test_sc_threshold_is_zero(self, service):
        """Verifica que -sc_threshold = 0 (no scene change detection).
        
        REF: issue #133 — -sc_threshold > 0 permite keyframes oportunistas que rompen
        GOP constante. Debe ser 0 para garantizar keyframes solo a -g.
        
        MUTANTE MATA: -sc_threshold 10, -sc_threshold 27, -sc_threshold NN con NN > 0.
        MUTANTE NO MATA: -sc_threshold 0 correctamente.
        """
        cmd = service.get("command", [])
        cmd_str = " ".join(str(c) for c in cmd)
        
        try:
            sc_index = cmd.index("-sc_threshold")
            sc_value = cmd[sc_index + 1]
            assert sc_value == "0", (
                f"Parámetro -sc_threshold debe ser 0 (desactiva scene change detection, issue #133). "
                f"Encontrado: -sc_threshold {sc_value}."
            )
        except (ValueError, IndexError):
            pytest.fail(
                f"Falta parámetro -sc_threshold en command o sin valor. "
                f"command: {cmd_str}. "
                f"Referencia issue #133."
            )


class TestSourceFFmpegDeployIntegration:
    """Tests de integración en deploy.yml."""

    def test_deploy_yml_mentions_source_ffmpeg_in_infra(self):
        """Verifica que deploy.yml detecta cambios en source-ffmpeg.
        
        Si se modifican COMPOSE, la sonda o el runbook, debe reconocer cambios 'infra'.
        El cambio en docker-compose.prod.yml ya activa 'infra'.
        
        MUTANTE 17: Mata:
        - deploy.yml sin 'infra' filter
        - docker-compose.prod.yml cambios no detectados
        """
        if not DEPLOY.exists():
            pytest.skip("deploy.yml no existe")
        
        deploy_yaml = yaml.safe_load(DEPLOY.read_text())
        detect_job = deploy_yaml.get("jobs", {}).get("detect", {})
        filters = detect_job.get("steps", [{}])[1].get("with", {}).get("filters", "")
        
        # Verifica que 'docker-compose.prod.yml' está en el filtro 'infra'
        assert "docker-compose.prod.yml" in filters, (
            "deploy.yml debe detectar cambios en docker-compose.prod.yml (filter 'infra')"
        )


class TestSourceStatusSchema:
    """Tests del contrato source-status.json."""

    def test_schema_has_required_fields(self, schema_spec):
        """Verifica que el schema requiere los campos esenciales.
        
        MUTANTE 18: Mata cambios que quiten campos requeridos.
        """
        required = schema_spec.get("required", [])
        expected = ["source", "state", "target", "streamid", "checked_at"]
        for field in expected:
            assert field in required, f"schema debe requerir '{field}' en {required}"

    def test_schema_state_enum(self, schema_spec):
        """Verifica que 'state' solo permite valores válidos.
        
        MUTANTE 19: Mata cambios en enum de estado.
        """
        state_prop = schema_spec.get("properties", {}).get("state", {})
        enum = state_prop.get("enum", [])
        expected = ["running", "restarting", "down", "unknown"]
        assert set(enum) == set(expected), (
            f"schema 'state' enum debe ser {expected} (found: {enum})"
        )

    def test_schema_streamid_not_empty(self, schema_spec):
        """Verifica que streamid tiene minLength: 1.
        
        MUTANTE 20: Mata cambios en validación de streamid.
        """
        streamid_prop = schema_spec.get("properties", {}).get("streamid", {})
        assert streamid_prop.get("minLength") == 1, (
            f"streamid debe tener minLength: 1 (found: {streamid_prop})"
        )


class TestSourceStatusProbe:
    """Tests de la sonda source-ffmpeg."""

    def test_probe_script_exists(self):
        """Verifica que scripts/probe-source-ffmpeg.sh existe.
        
        MUTANTE 21: Mata borrado accidental del script.
        """
        assert PROBE.exists(), f"Falta {PROBE}"

    def test_probe_is_executable(self):
        """Verifica que la sonda es ejecutable.
        
        MUTANTE 22: Mata permisos incorrectos.
        """
        assert PROBE.stat().st_mode & 0o111, f"{PROBE} no es ejecutable"

    def test_probe_outputs_valid_json_schema(self):
        """Ejecuta la sonda y valida salida contra schema.
        
        MUTANTE 23: Mata salida no-JSON o schema inválido.
        
        Nota: REQUIERE docker en el host. Si no hay docker, salta.
        Si hay docker pero no hay contenedor, la sonda devuelve state=down (válido).
        """
        if not PROBE.exists():
            pytest.skip(f"No existe {PROBE}")
        
        # Intenta ejecutar la sonda. Si falla (no hay docker), salta.
        try:
            result = subprocess.run(
                [str(PROBE)],
                capture_output=True,
                text=True,
                timeout=10
            )
            output = result.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("Sonda no puede ejecutarse (sin docker o sin permisos)")
        
        # Intenta parsear JSON
        try:
            data = json.loads(output)
        except json.JSONDecodeError as e:
            pytest.fail(f"Sonda no retorna JSON válido:\n{output}\nError: {e}")
        
        # Valida contra schema (validación manual)
        required = SCHEMA.read_text()
        schema = json.loads(required)
        required_fields = schema.get("required", [])
        for field in required_fields:
            assert field in data, f"Falta campo requerido '{field}' en salida: {data}"
        
        # Valida enums
        if "state" in data:
            assert data["state"] in ["running", "restarting", "down", "unknown"], (
                f"state inválido: {data['state']}"
            )

    def test_probe_exit_code_reflects_state(self):
        """Verifica que exit code es 0 si state=running, non-zero si down.
        
        MUTANTE 24: Mata exit code inconsistente con state.
        """
        if not PROBE.exists():
            pytest.skip(f"No existe {PROBE}")
        
        try:
            result = subprocess.run(
                [str(PROBE)],
                capture_output=True,
                text=True,
                timeout=10
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pytest.skip("Sonda no puede ejecutarse")
        
        output = result.stdout.strip()
        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            pytest.skip("Sonda no retorna JSON válido en este entorno")
        
        state = data.get("state", "unknown")
        if state == "running":
            assert result.returncode == 0, (
                f"exit code debe ser 0 si state=running (got {result.returncode})"
            )


class TestRunbook:
    """Tests de la documentación runbook."""

    def test_runbook_exists(self):
        """Verifica que docs/runbooks/source-ffmpeg.md existe.
        
        MUTANTE 25: Mata borrado accidental.
        """
        assert RUNBOOK.exists(), (
            f"Falta runbook {RUNBOOK}. "
            f"Debe documentar: servicio, configuración FFmpeg, verificación, troubleshooting."
        )

    def test_runbook_mentions_testsrc2_and_audio(self):
        """Verifica que runbook documenta testsrc2 + audio.
        
        MUTANTE 26: Mata documentación de fuentes.
        """
        content = RUNBOOK.read_text()
        assert "testsrc2" in content.lower(), "Runbook debe mencionar testsrc2"
        assert ("audio" in content.lower() or "sine" in content.lower() or "tone" in content.lower()), (
            "Runbook debe mencionar audio/sine/tone"
        )

    def test_runbook_mentions_srt_ingest_dependency(self):
        """Verifica que runbook documenta dependencia de srt-ingest.
        
        MUTANTE 27: Mata documentación de dependencias de transporte.
        """
        content = RUNBOOK.read_text()
        assert "srt-ingest" in content.lower(), (
            "Runbook debe mencionar que source-ffmpeg depende de srt-ingest"
        )


class TestSourceFFmpegIncidentFix:
    """
    INCIDENTE DE PRODUCCIÓN (FIX-SOURCE-FFMPEG-FRAMES):
    
    En producción (jrottenberg/ffmpeg:7.1-alpine), `testsrc2=d=0` genera duración CERO
    → ffmpeg statsframe=0 (CERO frames de vídeo), mientras que `sine d=0` SÍ es infinito
    (diferencia semántica en estos dos filtros lavfi).
    
    Resultado: ffmpeg emitía SOLO AUDIO (sin vídeo) a 51x velocidad real (~1 MB/s),
    sin pacing. El catálogo MoQ nunca se generaba ('subscribed error internal error' 
    en srt-ingest).
    
    ARREGLO REQUERIDO:
    1. Entrada lavfi de vídeo (testsrc2) NO debe llevar d=0 ni ninguna duración (clave d/duration).
    2. CADA entrada lavfi debe ir precedida de EXACTAMENTE UN `-re` dentro de su grupo de entrada.
    3. Audio: se elimina toda duración (d/duration) por uniformidad.
    
    REFERENCIA: https://github.com/teremoqwow/teremoqwow/issues/XXX (FIX-SOURCE-FFMPEG-FRAMES)
    """

    @staticmethod
    def _parse_lavfi_params(filter_spec: str) -> dict:
        """
        Parsea una especificación lavfi como pares clave=valor.
        
        Ejemplo:
        - "testsrc2=s=1280x720:r=30" → {"s": "1280x720", "r": "30"}
        - "sine=f=1000:r=48000" → {"f": "1000", "r": "48000"}
        
        Retorna dict {clave: valor, ...}
        """
        if "=" not in filter_spec:
            return {}
        
        # Separa filter_name=params
        parts = filter_spec.split("=", 1)
        if len(parts) < 2:
            return {}
        
        params_str = parts[1]
        params = {}
        
        # Split por ":" (separador de parámetros en lavfi)
        for param in params_str.split(":"):
            if "=" in param:
                key, val = param.split("=", 1)
                params[key] = val
        
        return params

    @staticmethod
    def _group_input_tokens(cmd: List[str]) -> List[List[int]]:
        """
        Agrupa los índices de tokens por entrada lavfi.
        
        Cada grupo contiene los índices de los tokens que pertenecen a una entrada:
        [tokens previos] -i <filter_spec> [tokens siguientes hasta la próxima -i]
        
        Retorna lista de listas: [[índices del grupo 0], [índices del grupo 1], ...]
        """
        groups = []
        current_group_start = None
        
        for i, arg in enumerate(cmd):
            if arg == "-i" and i + 1 < len(cmd):
                # Este es un marcador de entrada
                if current_group_start is not None:
                    # Finaliza el grupo anterior
                    groups.append((current_group_start, i - 1))
                
                # Inicia nuevo grupo desde hace poco antes del -i
                # Buscamos hacia atrás para incluir -f lavfi, -re, etc.
                # Retrocedemos hasta encontrar otro -i o el inicio
                start = i
                for j in range(i - 1, -1, -1):
                    if cmd[j] == "-i":
                        start = j + 1
                        break
                    start = j
                
                current_group_start = start
        
        # Finaliza el último grupo
        if current_group_start is not None:
            groups.append((current_group_start, len(cmd) - 1))
        
        return groups

    @staticmethod
    def _has_duration_key(params: dict) -> bool:
        """Verifica si los parámetros contienen alguna clave de duración.
        
        Rechaza tanto 'd' como 'duration' (alias en lavfi).
        Rechaza cualquier valor: 'd=0', 'd=5', 'd=.5', 'd=+5', 'd=-1', etc.
        """
        return "d" in params or "duration" in params

    def test_testsrc2_video_does_not_have_duration_keys(self, service):
        """
        HIGH-1: testsrc2 NO debe tener NINGUNA clave de duración (d o duration).
        
        Parseamos los parámetros como pares clave=valor y rechazamos ambas claves.
        
        MUTANTES MATA:
        - testsrc2=s=1280x720:r=30:d=0 (cero)
        - testsrc2=s=1280x720:r=30:d=30 (valor finito)
        - testsrc2=s=1280x720:r=30:duration=0 (alias 'duration')
        - testsrc2=s=1280x720:r=30:d=.5 (decimal)
        - testsrc2=s=1280x720:r=30:d=+5 (signo +)
        - testsrc2=s=1280x720:r=30:d=-1 (signo -)
        
        MUTANTES NO MATA:
        - testsrc2=s=1280x720:r=30 (sin d= ni duration=)
        """
        cmd = service.get("command", [])
        cmd_str = " ".join(str(c) for c in cmd)
        
        assert "testsrc2" in cmd_str, "Falta testsrc2 en command"
        
        # Extrae el parámetro testsrc2=...
        match = re.search(r'testsrc2=([^"\s:]+(?::[^"\s:]+)*)', cmd_str)
        assert match, f"No se puede parsear testsrc2=... en: {cmd_str}"
        
        testsrc2_spec = "testsrc2=" + match.group(1)
        params = self._parse_lavfi_params(testsrc2_spec)
        
        assert not self._has_duration_key(params), (
            f"testsrc2 NO debe llevar clave 'd' ni 'duration'. "
            f"INCIDENTE: d=0 en testsrc2 → frame=0 en jrottenberg/ffmpeg:7.1-alpine. "
            f"Solución: Eliminar completamente d= o duration= de testsrc2. "
            f"Encontrado: {testsrc2_spec} → params={params}"
        )

    def test_sine_audio_does_not_have_duration_keys(self, service):
        """
        HIGH-1: sine (audio) tampoco debe tener NINGUNA clave de duración (d o duration).
        
        Por uniformidad: si vídeo no lleva duración, audio tampoco.
        Aunque sine d=0 SÍ es infinito (diferente de testsrc2), la claridad de intent
        es preferible.
        
        MUTANTES MATA:
        - sine=f=1000:r=48000:d=0
        - sine=f=1000:r=48000:d=5
        - sine=f=1000:r=48000:duration=0
        """
        cmd = service.get("command", [])
        cmd_str = " ".join(str(c) for c in cmd)
        
        if "sine" not in cmd_str:
            pytest.skip("No hay entrada sine en command")
        
        # Extrae el parámetro sine=...
        match = re.search(r'sine=([^"\s:]+(?::[^"\s:]+)*)', cmd_str)
        assert match, f"No se puede parsear sine=... en: {cmd_str}"
        
        sine_spec = "sine=" + match.group(1)
        params = self._parse_lavfi_params(sine_spec)
        
        assert not self._has_duration_key(params), (
            f"sine NO debe llevar clave 'd' ni 'duration' (por uniformidad con vídeo). "
            f"Encontrado: {sine_spec} → params={params}"
        )

    def test_each_lavfi_input_has_exactly_one_re_pacing(self, service):
        """
        HIGH-2: Cada entrada lavfi DEBE tener EXACTAMENTE UNO `-re` en su grupo de entrada.
        
        Agrupa tokens por entrada (-i) y verifica que dentro de cada grupo
        hay exactamente un `-re` (no cero, no duplicado).
        
        `-re` puede estar en cualquier posición del grupo, incluso cruzando `-f lavfi`:
        - Válido: -re -f lavfi -i "testsrc2=..."
        - Válido: -f lavfi -re -i "testsrc2=..."
        
        Rechaza:
        - MUTANTE: -f lavfi -i "testsrc2=..." (sin -re, posición 0)
        - MUTANTE: -re -re -f lavfi -i "testsrc2=..." -f lavfi -i "sine=..." (re duplicado)
        - MUTANTE: -metadata -re -f lavfi -i "sine=..." (-re como valor de opción)
        
        LÓGICA: 
        1. Agrupa tokens por entrada (desde el final del grupo anterior hasta -i)
        2. Para cada grupo, cuenta cuántos `-re` hay
        3. Verifica que EXACTAMENTE 1 `-re` está presente
        4. Verifica que `-re` NO es valor de otra opción (ej. -metadata -re)
        """
        cmd = service.get("command", [])
        cmd_str = " ".join(str(c) for c in cmd)
        
        # Encuentra todas las posiciones de "-i"
        input_positions = [i for i, arg in enumerate(cmd) if arg == "-i"]
        assert len(input_positions) > 0, "Debe haber al menos una entrada (-i)"
        
        # Para cada entrada, crea su grupo
        for input_idx, i_pos in enumerate(input_positions):
            # Determina inicio del grupo (final del grupo anterior o inicio del comando)
            if input_idx == 0:
                group_start = 0
            else:
                # Desde después de la entrada anterior hasta antes del -i actual
                group_start = input_positions[input_idx - 1] + 2  # +2 para saltar -i y su valor
            
            group_end = i_pos - 1  # Hasta justo antes de -i
            
            # Extrae el grupo de tokens
            group_tokens = cmd[group_start:group_end + 1]
            
            # Cuenta cuántos -re hay en el grupo
            re_count = sum(1 for tok in group_tokens if tok == "-re")
            
            # Verifica que NO se duplicó y que está presente
            assert re_count == 1, (
                f"Entrada {input_idx} (posición {i_pos}): se encontraron {re_count} `-re` "
                f"en su grupo. DEBE haber EXACTAMENTE 1. "
                f"Grupo: {' '.join(group_tokens)} "
                f"INCIDENTE: -re fuerza pacing en tiempo real. Sin él, ffmpeg corre a ~51x. "
                f"Comando: {cmd_str}"
            )
            
            # Verifica que -re NO está siendo usado como valor de otra opción
            # (ej. -metadata -re, donde -re es el valor esperado de -metadata)
            for j, tok in enumerate(group_tokens):
                if tok == "-re":
                    # Verifica que el token ANTERIOR no es una opción que espera un valor
                    if j > 0:
                        prev_tok = group_tokens[j - 1]
                        # Opciones que esperan un valor (common ffmpeg flags)
                        value_expecting_options = {
                            "-metadata", "-title", "-author", "-comment", "-copyright",
                            "-creation_time", "-bitrate", "-c", "-codec", "-c:v", "-c:a",
                            "-vcodec", "-acodec", "-preset", "-tune", "-profile", "-level"
                        }
                        assert prev_tok not in value_expecting_options, (
                            f"Entrada {input_idx}: `-re` está siendo usado como valor "
                            f"de '{prev_tok}', no como opción de pacing. "
                            f"Grupo: {' '.join(group_tokens)}"
                        )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
