#!/usr/bin/env bash
# renew-dev-certs.sh — Genera cert TLS dev de 14 días para WebTransport.
# WebTransport (Chrome) rechaza certs autofirmados con validez > 14 días.
# Uso: bash scripts/renew-dev-certs.sh (desde la raíz del repo)
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="${REPO_ROOT}/config/relay/certs"
CERT_PEM="${CERT_DIR}/relay.pem"
CERT_KEY="${CERT_DIR}/relay.key"
ENV_FILE="${REPO_ROOT}/.env.dev-cert"

echo "→ Generando certificado EC P-256 con validez 14 días…"
openssl req -x509 \
  -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
  -keyout "${CERT_KEY}" \
  -out    "${CERT_PEM}" \
  -days 14 \
  -nodes \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
  2>/dev/null

echo "→ Calculando fingerprint SHA-256…"
FINGERPRINT=$(openssl x509 -in "${CERT_PEM}" -noout -fingerprint -sha256 \
  | tr -d ':' | awk -F= '{print tolower($2)}')

echo "   RELAY_CERT_SHA256=${FINGERPRINT}"

# Actualiza (o crea) .env.dev-cert; preserva otras variables si ya existe.
if [[ -f "${ENV_FILE}" ]]; then
  # Reemplaza la línea existente sin borrar el resto del fichero.
  sed -i "s|^RELAY_CERT_SHA256=.*|RELAY_CERT_SHA256=${FINGERPRINT}|" "${ENV_FILE}"
  if ! grep -q "^RELAY_CERT_SHA256=" "${ENV_FILE}"; then
    echo "RELAY_CERT_SHA256=${FINGERPRINT}" >> "${ENV_FILE}"
  fi
else
  echo "RELAY_CERT_SHA256=${FINGERPRINT}" > "${ENV_FILE}"
fi

echo "→ ${ENV_FILE} actualizado."
echo ""
echo "Cert expira en 14 días. Vuelve a ejecutar este script antes de que caduque."
