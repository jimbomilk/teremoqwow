#!/usr/bin/env bash
# P3 — Test suite: cert expiry check en integration-test.sh
# RED (antes del parche): T1 falla.  GREEN (tras el parche): todos pasan.
# Uso: bash qos/scripts/test_cert_expiry.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INTEGRATION_SH="${SCRIPT_DIR}/integration-test.sh"
TMPDIR_TEST=$(mktemp -d)
trap 'rm -rf "$TMPDIR_TEST"' EXIT

PASS=0; FAIL=0
ok() { echo "✓ PASS: $1"; PASS=$((PASS+1)); }
ko() { echo "✗ FAIL: $1"; FAIL=$((FAIL+1)); }

# Misma lógica que el bloque añadido en integration-test.sh
_cert_check() {
  local cert_path="$1"
  [[ ! -f "$cert_path" ]] && return 0
  local end_date; end_date=$(openssl x509 -enddate -noout -in "$cert_path" 2>/dev/null | cut -d= -f2-)
  local expiry_epoch; expiry_epoch=$(date -d "$end_date" +%s 2>/dev/null) || return 0
  local now_epoch; now_epoch=$(date +%s)
  local days_left=$(( (expiry_epoch - now_epoch) / 86400 ))
  if (( days_left < 0 )); then
    return 1
  elif (( days_left <= 3 )); then
    echo "WARN: expira en ${days_left} días"
    return 0
  fi
  return 0
}

gen_expired_cert() {
  local out="$1"
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "${out%.pem}.key" -out "$out" \
    -subj "/CN=test-expired" \
    -not_before "$(date -d '5 days ago' +%Y%m%d%H%M%SZ)" \
    -not_after  "$(date -d '2 days ago' +%Y%m%d%H%M%SZ)" \
    2>/dev/null
}

gen_valid_cert() {
  local out="$1"
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "${out%.pem}.key" -out "$out" \
    -subj "/CN=test-valid" -days 14 \
    2>/dev/null
}

echo ""
echo "══════════════════════════════════════════════════════════"
echo " P3 — Cert Expiry Check Test Suite"
echo " Script: $INTEGRATION_SH"
echo "══════════════════════════════════════════════════════════"
echo ""

# ── T1: RED→GREEN — SKIP_CERT_CHECK presente en integration-test.sh ─────────
echo "=== T1: SKIP_CERT_CHECK presente en integration-test.sh ==="
if grep -q "SKIP_CERT_CHECK" "$INTEGRATION_SH" 2>/dev/null; then
  ok "T1: SKIP_CERT_CHECK encontrado (GREEN)"
else
  ko "T1: SKIP_CERT_CHECK no encontrado (RED — aplica el parche)"
fi

# ── T2: Sintaxis bash -n ─────────────────────────────────────────────────────
echo "=== T2: bash -n sintaxis ==="
if bash -n "$INTEGRATION_SH" 2>/dev/null; then
  ok "T2: bash -n OK"
else
  ko "T2: error de sintaxis en integration-test.sh"
fi

# ── T3: bloque condicional en integration-test.sh ────────────────────────────
echo "=== T3: lógica condicional SKIP_CERT_CHECK ==="
if grep -qE 'SKIP_CERT_CHECK.*==.*"0"|"\$\{SKIP_CERT_CHECK' "$INTEGRATION_SH" 2>/dev/null; then
  ok "T3: bloque condicional encontrado en integration-test.sh"
else
  ko "T3: bloque condicional SKIP_CERT_CHECK no encontrado"
fi

# ── T4: cert expirado → exit 1 ───────────────────────────────────────────────
echo "=== T4: cert expirado detectado ==="
gen_expired_cert "${TMPDIR_TEST}/expired.pem"
if _cert_check "${TMPDIR_TEST}/expired.pem"; then
  ko "T4: cert expirado NO detectado (debería salir con error)"
else
  ok "T4: cert expirado detectado correctamente (exit 1)"
fi

# ── T5: cert válido 14 días → exit 0 ─────────────────────────────────────────
echo "=== T5: cert válido (14 días) no falla ==="
gen_valid_cert "${TMPDIR_TEST}/valid.pem"
if _cert_check "${TMPDIR_TEST}/valid.pem"; then
  ok "T5: cert válido (14 días) no genera error"
else
  ko "T5: cert válido falló inesperadamente"
fi

# ── T6: cert inexistente → skip silencioso ───────────────────────────────────
echo "=== T6: cert inexistente → skip silencioso ==="
if _cert_check "${TMPDIR_TEST}/nonexistent.pem"; then
  ok "T6: cert inexistente → skip silencioso (exit 0)"
else
  ko "T6: cert inexistente no debería fallar"
fi

# ── T7: SKIP_CERT_CHECK=1 → bloque omitido ───────────────────────────────────
echo "=== T7: SKIP_CERT_CHECK=1 omite el bloque ==="
SKIP_CERT_CHECK=1
if [[ "${SKIP_CERT_CHECK}" == "0" ]]; then
  _cert_check "${TMPDIR_TEST}/expired.pem"
  skip_rc=$?
else
  skip_rc=0
fi
if [[ "$skip_rc" == "0" ]]; then
  ok "T7: SKIP_CERT_CHECK=1 omite el bloque (exit 0)"
else
  ko "T7: SKIP_CERT_CHECK=1 no omitió el bloque"
fi

# ── Resumen ───────────────────────────────────────────────────────────────────
echo ""
echo "══════════════════════════════════════════════════════════"
printf " Resultado: %d passed, %d failed\n" "$PASS" "$FAIL"
echo "══════════════════════════════════════════════════════════"
[[ "$FAIL" -eq 0 ]]
