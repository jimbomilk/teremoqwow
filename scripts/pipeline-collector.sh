#!/usr/bin/env bash
# Colector del host de producción para la vista Admin Pipeline (#214).
#
# SOLO MIDE. La derivación a observaciones vive en pipeline_obs.py (función pura).
# Salida: 9 líneas JSON (una por señal) por stdout, para
#   scripts/pipeline-collector.sh | docker compose ... exec -T admin-api python /app/pipeline_ingest.py
#
# Mide TRANSPORTE (llegada de bytes / HTTP). Jamás calidad audiovisual: sin
# ffprobe/ffmpeg/frames/códec.
#
# Mediciones:
#   - Dos sesiones moq, una por broadcast (anon/live1 y anon/live1-meta), cada una
#     con ventana REAL de 20 s (timeout -s INT 20 docker run ... export ts).
#     stdout -> pipeline_ts_count.py; stderr -> fichero aparte (NUNCA contado
#     como bytes). Sin --net host: el cliente solo sale a wow.teremoq.com:4443.
#   - curl a /api/cert-hash (relay.public) y /player/ (player.http), max 10 s.
# Criterio de "conectó": ver pipeline_obs.py (session_connected). Si no conectó,
# las señales dependientes salen UNKNOWN; docker ausente -> UNKNOWN; curl rc!=0 ->
# UNKNOWN. Nunca PASS/FAIL inventado.
#
# CONTRATO DE EXIT CODES (siempre 9 líneas JSON por stdout, una por señal):
#   0  = derivación normal (assemble|derive de Python devolvió exactamente 9
#        líneas), aun cuando algunas/todas las señales sean UNKNOWN.
#   3  = fallo del PROPIO colector (Python ausente/falló, salida != 9 líneas,
#        sin directorio temporal). Aun así se emiten 9 líneas UNKNOWN con un
#        método independiente de Python (printf, literales fijos, sin datos
#        externos interpolados) para que `set -o pipefail` falle el workflow y
#        las señales previas no caduquen en silencio.
#   143 = terminado por TERM/INT/HUP (el trap limpia contenedores).
# Duración máx.: 2*(20+5) s + 2*10 s < 3 min.
# Variable opcional PYTHON3 (por defecto python3).
# Hook de test (NO usado en producción ni por el workflow): solo con
# PIPELINE_COLLECTOR_TEST_MODE=1 se leen PIPELINE_WINDOW_SECONDS y
# PIPELINE_GRACE_SECONDS, y solo se aceptan enteros 1..20 / 1..5 (cotas de
# producción); cualquier otro valor => 20 / 5.

set -u -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON3:-python3}"
IMAGE="moqdev/moq:0.12.7"
URL_MOQ="https://wow.teremoq.com:4443/anon"
WINDOW=20
GRACE=5
EXIT_COLLECTOR_FAILURE=3

if [ "${PIPELINE_COLLECTOR_TEST_MODE:-}" = "1" ]; then
  case "${PIPELINE_WINDOW_SECONDS:-}" in
    [1-9]|1[0-9]|20) WINDOW="$PIPELINE_WINDOW_SECONDS" ;;
  esac
  case "${PIPELINE_GRACE_SECONDS:-}" in
    [1-5]) GRACE="$PIPELINE_GRACE_SECONDS" ;;
  esac
fi

TMP="$(mktemp -d 2>/dev/null)" || TMP=""
NAMES=()

cleanup() {
  local n
  if command -v docker >/dev/null 2>&1; then
    for n in "${NAMES[@]:-}"; do
      [ -n "$n" ] && timeout 10 docker rm -f "$n" >/dev/null 2>&1
    done
  fi
  [ -n "$TMP" ] && rm -rf "$TMP"
  return 0
}
trap cleanup EXIT
trap 'exit 143' TERM INT HUP

# measure_session <tag> <broadcast>
measure_session() {
  local tag="$1" broadcast="$2" name rcs
  name="pipeline-collector-$$-${tag}"
  NAMES+=("$name")
  timeout -k "$GRACE" -s INT "$WINDOW" docker run --rm --name "$name" "$IMAGE" \
    --connect "$URL_MOQ" --broadcast "$broadcast" export ts \
    2>"$TMP/${tag}.stderr" \
    | "$PY" "$SCRIPT_DIR/pipeline_ts_count.py" >"$TMP/${tag}.ts.json" 2>>"$TMP/${tag}.stderr"
  rcs=("${PIPESTATUS[@]}")
  printf '%s\n' "${rcs[0]}" >"$TMP/${tag}.rc"
}

# measure_http <stem> <url>
measure_http() {
  local stem="$1" url="$2" code rc
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 10 "$url" 2>/dev/null)"
  rc=$?
  printf '%s\n' "$rc" >"$TMP/${stem}.curl_rc"
  printf '%s\n' "$code" >"$TMP/${stem}.http_code"
}

measure() {
  [ -n "$TMP" ] || return 1
  if command -v docker >/dev/null 2>&1; then
    printf '1\n' >"$TMP/docker_available"
    measure_session live1 anon/live1
    measure_session meta anon/live1-meta
  else
    printf '0\n' >"$TMP/docker_available"
  fi
  measure_http relay_public "https://wow.teremoq.com/api/cert-hash"
  measure_http player_http "https://wow.teremoq.com/player/"
}

# 9 líneas UNKNOWN sin Python: JSON de literales fijos (sin datos externos).
emit_fallback() {
  local at sig reason
  at="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"
  case "$at" in
    [0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9]Z) ;;
    *) printf -v at '%(%Y-%m-%dT%H:%M:%SZ)T' -1 ;;
  esac
  reason="No medible: el colector no pudo derivar las observaciones (Python no disponible o fallo interno); no se afirma nada sobre el flujo."
  for sig in ingest.video ingest.audio ingest.data relay.public relay.announce \
             relay.catalog relay.tracks player.http player.subscribe; do
    printf '{"signal": "%s", "result": "UNKNOWN", "observed_at": "%s", "reason": "%s"}\n' \
      "$sig" "$at" "$reason"
  done
}

main() {
  local out lines
  measure || true
  if [ -n "$TMP" ]; then
    # Salida capturada: solo se imprime si assemble|derive terminó bien y son 9 líneas.
    if out="$("$PY" "$SCRIPT_DIR/pipeline_obs.py" assemble --dir "$TMP" \
        | "$PY" "$SCRIPT_DIR/pipeline_obs.py" derive 2>/dev/null)"; then
      mapfile -t lines <<<"$out"
      if [ "${#lines[@]}" -eq 9 ]; then
        printf '%s\n' "$out"
        return 0
      fi
    fi
  fi
  emit_fallback
  return "$EXIT_COLLECTOR_FAILURE"
}

main
exit $?
