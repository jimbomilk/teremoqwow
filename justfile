# teremoqwow — targets de desarrollo
# Uso: just <target>
# Instalar just: https://github.com/casey/just

# Levantar el stack completo en background
dev:
    cp -n .env.example .env 2>/dev/null || true
    docker compose up -d
    @echo ""
    @echo "Stack levantado:"
    @echo "  Player:         http://localhost:5173"
    @echo "  Grafana:        http://localhost:3000  (admin / dev-grafana)"
    @echo "  Prometheus:     http://localhost:9090"
    @echo "  MoQ Relay web:  http://localhost:8090"
    @echo "  Auth API:       http://localhost:9002/health"
    @echo "  Portal API:     http://localhost:9003/health"
    @echo "  KrakenD:        http://localhost:8080/health"
    @echo ""
    @echo "Para inyectar video: just inject"

# Parar todos los servicios
stop:
    docker compose down

# Inyectar stream de prueba (FFmpeg → MoQ relay)
inject:
    docker run --rm \
      --name teremoqwow-inject \
      --network teremoqwow-dev \
      linuxserver/ffmpeg:latest \
      -re \
      -f lavfi -i "testsrc2=size=1280x720:rate=30" \
      -f lavfi -i "sine=frequency=1000:sample_rate=48000" \
      -c:v libx264 -preset ultrafast -tune zerolatency \
      -profile:v main -level 4.0 -g 15 -keyint_min 15 -sc_threshold 0 \
      -c:a aac -b:a 128k \
      -f mpegts pipe:1 2>/dev/null | \
    docker run --rm -i \
      --network teremoqwow-dev \
      moqdev/moq:0.12.7 \
      --connect tcp://moq-relay:4444/anon \
      --broadcast anon/live1 \
      import ts 2>&1

# Ejecutar todos los tests (unitarios + integration)
test: test-drm qos-test

# Tests DRM/Auth/Portal
test-drm:
    pip install flask PyJWT cryptography jsonschema redis --quiet 2>/dev/null
    openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
      -out /tmp/just-test.pem 2>/dev/null
    JWT_RS256_PRIVATE_KEY_PATH=/tmp/just-test.pem bash comercial/billing/test_drm_flow.sh

# Integration test QoS (requiere relay activo — ejecutar `just dev` antes)
qos-test:
    SKIP_NETEM=1 WINDOW_SEC=15 timeout 180 bash qos/scripts/integration-test.sh

# Ver logs de un servicio
logs service="moq-relay":
    docker compose logs -f {{service}}

# Regenerar certificados TLS de desarrollo (válidos 13 días — WebTransport limit)
certs:
    bash scripts/renew-dev-certs.sh

# Estado de todos los contenedores
status:
    docker compose ps

# Limpiar: parar y borrar volúmenes
clean:
    docker compose down -v
    @echo "Stack limpiado (volúmenes eliminados)"

# Rebuild de todos los servicios (tras cambios en código)
build:
    docker compose build --parallel

# Abrir player en el browser (Linux)
open:
    xdg-open http://localhost:5173 2>/dev/null || echo "Abre http://localhost:5173 en tu browser"

# Login de admin (obtiene token JWT)
login:
    @curl -s -X POST http://localhost:9002/auth/login \
      -H "Content-Type: application/json" \
      -d '{"email":"admin@teremoqwow.dev","password":"dev-secret"}' | python3 -m json.tool
# Compartir el player en la red local — accesible desde otro ordenador via HTTPS+MoQ
# Uso: just share [broadcast]
# En el otro ordenador abre la URL que se imprime en Chrome/Edge
share broadcast="anon/live1":
    #!/usr/bin/env bash
    set -e
    HOST_IP=$(hostname -I | awk '{print $1}')
    CERT_HASH=$(openssl x509 -in config/relay/certs/relay.pem -noout -fingerprint -sha256 \
      | tr -d ':' | awk -F= '{print tolower($2)}')
    RELAY_URL="https://${HOST_IP}:4443/anon"
    PLAYER_URL="https://${HOST_IP}:5443?relay=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${RELAY_URL}'))")&broadcast=$(python3 -c "import urllib.parse; print(urllib.parse.quote('{{broadcast}}'))")&cert=${CERT_HASH}"
    echo ""
    echo "═══════════════════════════════════════════════════════"
    echo "  teremoqwow — Player compartido en red local"
    echo "═══════════════════════════════════════════════════════"
    echo ""
    echo "  Player URL (abre en Chrome/Edge en el otro ordenador):"
    echo "  ${PLAYER_URL}"
    echo ""
    echo "  Relay MoQ:  ${RELAY_URL}"
    echo "  Broadcast:  {{broadcast}}"
    echo "  Cert hash:  ${CERT_HASH}"
    echo ""
    echo "  IMPORTANTE — En Windows abre el puerto del relay:"
    echo "  netsh advfirewall firewall add rule name=moq-relay protocol=UDP dir=in action=allow localport=4443"
    echo "  netsh advfirewall firewall add rule name=moq-player protocol=TCP dir=in action=allow localport=5443"
    echo ""
    echo "  Iniciando player HTTPS en ${HOST_IP}:5443 ..."
    echo "═══════════════════════════════════════════════════════"
    echo ""
    cd player && VITE_HTTPS=1 \
      VITE_MOQ_RELAY_URL=${RELAY_URL} \
      VITE_RELAY_BROADCAST={{broadcast}} \
      VITE_MOQ_CERT_HASH=${CERT_HASH} \
      npm run dev -- --host 2>&1
# ── Producción ──────────────────────────────────────────────────────────────

# Estado de producción (requiere SSH al servidor)
prod-status host="deploy@teremoqwow.dev":
    ssh {{host}} "cd /opt/teremoqwow && docker compose -f docker-compose.prod.yml ps"

# Logs de producción
prod-logs host="deploy@teremoqwow.dev" service="":
    ssh {{host}} "cd /opt/teremoqwow && docker compose -f docker-compose.prod.yml logs -f {{service}}"

# Health check de producción
prod-health host="deploy@teremoqwow.dev":
    ssh {{host}} "bash /opt/teremoqwow/scripts/prod-health-check.sh"

# Reiniciar un servicio en producción
prod-restart host="deploy@teremoqwow.dev" service="":
    ssh {{host}} "cd /opt/teremoqwow && docker compose -f docker-compose.prod.yml restart {{service}}"

# Rollback al commit anterior
prod-rollback host="deploy@teremoqwow.dev":
    ssh {{host}} "cd /opt/teremoqwow && git reset --hard HEAD~1 && docker compose -f docker-compose.prod.yml up -d"

# Renovar certificados TLS en producción
prod-certs host="deploy@teremoqwow.dev":
    ssh {{host}} "certbot renew && docker compose -f /opt/teremoqwow/docker-compose.prod.yml exec nginx nginx -s reload"
