#!/bin/bash
# Sonda de fuente FFmpeg en producción
# Consulta el estado del contenedor source-ffmpeg y emite JSON conforme a
# schemas/media/v1/source-status.json
#
# Alcance: solo camino de datos (contenedor vivo, destino SRT, reinicios).
# No inspecciona el contenido audiovisual; eso se confirma abriendo el player.
#
# Salida: JSON a stdout
# Exit: 0 si state=running, no-cero en otro caso

set -o pipefail

COMPOSE_FILE="${COMPOSE_FILE:-/opt/teremoqwow/docker-compose.prod.yml}"
PROJECT_NAME="${PROJECT_NAME:-teremoqwow}"

# Intenta obtener el estado del contenedor via docker compose
# Si docker no está disponible, retorna state=unknown
get_container_state() {
    local container_name="${PROJECT_NAME}-source-ffmpeg-1"
    
    if ! command -v docker &>/dev/null; then
        echo "unknown"
        return
    fi
    
    # Verifica si el contenedor existe y su estado
    local state
    state=$(docker ps -a --filter "name=${container_name}" --format "{{.State}}" 2>/dev/null)
    
    if [ -z "$state" ]; then
        echo "unknown"
    else
        echo "$state"
    fi
}

get_restart_count() {
    local container_name="${PROJECT_NAME}-source-ffmpeg-1"
    
    if ! command -v docker &>/dev/null; then
        echo "0"
        return
    fi
    
    # docker inspect retorna RestartCount
    docker inspect --format='{{.RestartCount}}' "${container_name}" 2>/dev/null || echo "0"
}

# ISO-8601 timestamp
current_timestamp() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# Construye JSON
main() {
    local state
    local restart_count
    local timestamp
    local error_msg=""
    local exit_code=0
    
    state=$(get_container_state)
    restart_count=$(get_restart_count)
    timestamp=$(current_timestamp)
    
    # Normaliza el estado de docker a nuestro enum
    case "$state" in
        running)
            state="running"
            ;;
        restarting)
            state="restarting"
            ;;
        exited|paused|dead)
            state="down"
            exit_code=1
            ;;
        unknown|"")
            state="unknown"
            exit_code=1
            error_msg="No se pudo determinar el estado del contenedor"
            ;;
        *)
            state="unknown"
            exit_code=1
            error_msg="Estado inesperado: $state"
            ;;
    esac
    
    # Construye JSON output
    local json="{
  \"source\": \"source-ffmpeg\",
  \"state\": \"$state\",
  \"target\": \"srt-ingest:8890\",
  \"streamid\": \"live1\",
  \"broadcast\": \"anon/live1\",
  \"restart_count\": $restart_count,
  \"checked_at\": \"$timestamp\""
    
    if [ -n "$error_msg" ]; then
        json="$json,
  \"error\": \"$error_msg\""
    fi
    
    json="$json
}"
    
    echo "$json"
    return $exit_code
}

main "$@"
