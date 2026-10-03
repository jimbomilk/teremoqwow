#!/usr/bin/env bash
# Verifica que todos los servicios de producción responden.
# Uso: bash scripts/prod-health-check.sh [--timeout 60]
# Exit 0 = todo OK. Exit 1 = algún servicio no responde.

set -euo pipefail

TIMEOUT=${2:-60}
PASS=0
FAIL=0

check() {
    local name="$1" url="$2"
    local deadline=$(( $(date +%s) + TIMEOUT ))
    while [[ $(date +%s) -lt $deadline ]]; do
        if curl -sf --max-time 5 "$url" > /dev/null 2>&1; then
            echo "  ✅ $name"
            PASS=$(( PASS + 1 ))
            return 0
        fi
        sleep 3
    done
    echo "  ❌ $name ($url) — sin respuesta en ${TIMEOUT}s"
    FAIL=$(( FAIL + 1 ))
    return 1
}

echo "=== teremoqwow production health check ==="
echo ""

# Servicios internos (se ejecuta desde el host del servidor)
check "moq-relay (web)"    "http://localhost:8090/"
check "krakend"            "http://localhost:8080/health"
check "billing-webhook"   "http://localhost:9000/health"
check "registry-server"   "http://localhost:9001/health"
check "auth"               "http://localhost:9002/health"
check "portal"             "http://localhost:9003/health"
check "admin-api"          "http://localhost:9004/health"
check "redis"              "http://localhost:6379" || \
    docker exec "$(docker compose -f docker-compose.prod.yml ps -q redis)" \
        redis-cli ping | grep -q PONG && echo "  ✅ redis (ping)" && PASS=$(( PASS+1 )) || true
check "clickhouse"         "http://localhost:8123/ping"
check "prometheus"         "http://localhost:9090/-/healthy"
check "grafana"            "http://localhost:3000/api/health"
check "nginx (HTTP→HTTPS)" "http://localhost:80/"
check "nginx (HTTPS)"      "https://localhost:443/" || true  # puede fallar si no hay cert válido aún

echo ""
echo "=== Resultado: $PASS OK, $FAIL FAIL ==="
[[ $FAIL -eq 0 ]]
