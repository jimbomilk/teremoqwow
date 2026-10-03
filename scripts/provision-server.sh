#!/usr/bin/env bash
# Provisioning inicial del servidor Vultr (Ubuntu 22.04 LTS).
# Ejecutar UNA SOLA VEZ como root tras crear el servidor.
# Uso: bash provision-server.sh teremoqwow.dev

set -euo pipefail

DOMAIN="${1:?Uso: $0 <dominio> ej. teremoqwow.dev}"

echo "=== Provisioning teremoqwow en $DOMAIN ==="

# ── Sistema base ──────────────────────────────────────────────────────────────
apt-get update -qq && apt-get upgrade -y -qq
apt-get install -y -qq curl git ufw fail2ban

# ── Docker ────────────────────────────────────────────────────────────────────
curl -fsSL https://get.docker.com | sh
systemctl enable --now docker

# ── Firewall ──────────────────────────────────────────────────────────────────
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 80/tcp
ufw allow 443/tcp
ufw allow 4443/tcp    # MoQ WebTransport (TCP)
ufw allow 4443/udp    # MoQ WebTransport (QUIC)
ufw --force enable

# ── Usuario de deploy ─────────────────────────────────────────────────────────
useradd -m -s /bin/bash deploy 2>/dev/null || true
usermod -aG docker deploy
mkdir -p /home/deploy/.ssh
echo "# Pegar aquí la clave pública del GitHub Actions deploy key" \
    >> /home/deploy/.ssh/authorized_keys
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
chown -R deploy:deploy /home/deploy/.ssh

# ── Directorio del proyecto ───────────────────────────────────────────────────
mkdir -p /opt/teremoqwow
chown deploy:deploy /opt/teremoqwow

# ── Clonar repo (deploy hace el clone con su clave) ──────────────────────────
# (se ejecutará en el primer deploy de GitHub Actions)

# ── Directorio de secretos ────────────────────────────────────────────────────
mkdir -p /etc/teremoqwow
chmod 700 /etc/teremoqwow
cat > /etc/teremoqwow/.env << 'ENVEOF'
# Rellenar con los valores reales antes del primer deploy
DOMAIN=teremoqwow.dev
LLM_PROVIDER=gemini
GEMINI_API_KEY=
GEMINI_MODEL=gemini-3.5-flash-lite
WEBHOOK_SECRET=
JWT_RS256_PRIVATE_KEY_PATH=/etc/teremoqwow/private.pem
REGISTRY_PRIVATE_KEY_PATH=/etc/teremoqwow/private.pem
REDIS_URL=redis://redis:6379/0
CLICKHOUSE_URL=http://clickhouse:8123
CLICKHOUSE_DB=teremoqwow
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=
GRAFANA_USER=admin
GRAFANA_PASSWORD=
STRIPE_SECRET_KEY=
MOESIF_APPLICATION_ID=
ENVEOF
chmod 600 /etc/teremoqwow/.env

# ── Red Docker de producción ──────────────────────────────────────────────────
docker network create teremoqwow-prod 2>/dev/null || true

# ── Certbot (Let's Encrypt) ───────────────────────────────────────────────────
apt-get install -y -qq certbot
mkdir -p /var/www/certbot
# Ejecutar manualmente después de que el DNS apunte al servidor:
# certbot certonly --standalone -d $DOMAIN -d www.$DOMAIN --agree-tos -m admin@$DOMAIN

# ── Cron para renovación de certs ────────────────────────────────────────────
echo "0 3 * * * root certbot renew --quiet && docker compose -f /opt/teremoqwow/docker-compose.prod.yml exec nginx nginx -s reload" \
    > /etc/cron.d/certbot-renew

echo ""
echo "=== Provisioning completado ==="
echo ""
echo "Pasos manuales pendientes:"
echo "  1. Apunta el DNS de $DOMAIN a esta IP: $(curl -s ifconfig.me)"
echo "  2. Añade la clave pública del deploy key a /home/deploy/.ssh/authorized_keys"
echo "  3. Rellena /etc/teremoqwow/.env con los valores reales"
echo "  4. Genera el certificado TLS:"
echo "     certbot certonly --standalone -d $DOMAIN --agree-tos -m admin@$DOMAIN"
echo "  5. Genera la clave RSA para JWT:"
echo "     openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out /etc/teremoqwow/private.pem"
echo ""
echo "El primer deploy lo hará GitHub Actions automáticamente en el próximo push a main."
