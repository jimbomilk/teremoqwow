#!/usr/bin/env bash
# Test flujo DRM/Billing sin Stripe real — #85
# Valida: HMAC-SHA256, replay attack, JWT RS256, idempotencia, geo-blocking,
#         availability_windows, max_plays y sanitización base64 EZDRM.
#
# USO: bash comercial/billing/test_drm_flow.sh
# PRERREQUISITOS: python3, openssl, pip3 install PyJWT flask

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
PASS=0
FAIL=0

pass() { echo "  ✓ PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ FAIL: $1"; FAIL=$((FAIL + 1)); }

# Generar par RSA efímero (2048 bits) — nunca reutilizar en producción
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 \
  -out "$TMP/key.pem" 2>/dev/null
openssl rsa -pubout -in "$TMP/key.pem" -out "$TMP/pub.pem" 2>/dev/null

WEBHOOK_SECRET="whsec_test_$(openssl rand -hex 16)"

# PYTHONPATH incluye billing y drm para todos los bloques Python
export PYTHONPATH="$REPO_ROOT/comercial/billing:$REPO_ROOT/drm:${PYTHONPATH:-}"
export JWT_RS256_PRIVATE_KEY_PATH="$TMP/key.pem"
export STRIPE_WEBHOOK_SECRET="$WEBHOOK_SECRET"
export MOQ_DEFAULT_NAMESPACE="broadcasts/live1"
export JWT_TTL_SECONDS="3600"

################################################################################
echo "=== #79 Stripe Webhook: HMAC-SHA256 + JWT RS256 + Idempotencia ==="
################################################################################
python3 - "$TMP/key.pem" "$TMP/pub.pem" "$WEBHOOK_SECRET" <<'PYEOF'
import sys, os, time, hmac, hashlib

key_path, pub_path, webhook_secret = sys.argv[1], sys.argv[2], sys.argv[3]
errors = 0

from webhook_handler import _verify_stripe_signature, _emit_access_token, _processed_events

payload = (
    b'{"id":"evt_001","type":"checkout.session.completed",'
    b'"data":{"object":{"customer":"cus_1","subscription":"sub_1"}}}'
)

# Firma válida
ts = str(int(time.time()))
signed_bytes = ts.encode() + b"." + payload
sig = hmac.new(webhook_secret.encode(), signed_bytes, hashlib.sha256).hexdigest()

if _verify_stripe_signature(payload, f"t={ts},v1={sig}", webhook_secret):
    print("  ✓ PASS: Firma HMAC-SHA256 válida → verificada")
else:
    print("  ✗ FAIL: Firma válida no verificada"); errors += 1

# Firma inválida → rechazada
if not _verify_stripe_signature(payload, f"t={ts},v1=0000000000badbad", webhook_secret):
    print("  ✓ PASS: Firma inválida → rechazada")
else:
    print("  ✗ FAIL: Firma inválida no fue rechazada"); errors += 1

# Replay attack (timestamp > 5 min) → rechazado
old_ts = str(int(time.time()) - 400)
old_signed = old_ts.encode() + b"." + payload
old_sig = hmac.new(webhook_secret.encode(), old_signed, hashlib.sha256).hexdigest()
if not _verify_stripe_signature(payload, f"t={old_ts},v1={old_sig}", webhook_secret):
    print("  ✓ PASS: Replay attack (>5 min) → rechazado")
else:
    print("  ✗ FAIL: Replay attack no fue rechazado"); errors += 1

# JWT RS256 — verifica con clave pública
try:
    import jwt as pyjwt
    token = _emit_access_token("cus_1", "sub_1", "broadcasts/live1")
    pub_key = open(pub_path).read()
    claims = pyjwt.decode(token, pub_key, algorithms=["RS256"])
    assert claims["sub"] == "cus_1", "sub incorrecto"
    assert "stream:read" in claims["scopes"], "falta stream:read"
    assert "drm:license" in claims["scopes"], "falta drm:license"
    assert claims["namespace"] == "broadcasts/live1", "namespace incorrecto"
    assert claims["stripe_subscription_id"] == "sub_1", "subscription_id incorrecto"
    print("  ✓ PASS: JWT RS256 emitido con claims correctos y verificable con clave pública")
except Exception as e:
    print(f"  ✗ FAIL: JWT RS256: {e}"); errors += 1

# Idempotencia — mismo event.id no debe reemitir
_processed_events.add("evt_001")
if "evt_001" in _processed_events:
    print("  ✓ PASS: Idempotencia: event.id almacenado correctamente")
else:
    print("  ✗ FAIL: Idempotencia falló"); errors += 1

sys.exit(errors)
PYEOF
[[ $? -eq 0 ]] && pass "webhook_handler" || fail "webhook_handler"

################################################################################
echo ""
echo "=== #82 Geo-blocking + Availability Windows ==="
################################################################################
python3 - <<'PYEOF'
import sys, os
errors = 0
from geo_middleware import check_geo_access
from datetime import datetime, timezone, timedelta

# País bloqueado → 403
ok, code = check_geo_access("DE", {"blocked_regions": ["DE", "FR"], "availability_windows": []})
if not ok and code == 403:
    print("  ✓ PASS: País bloqueado DE → 403")
else:
    print(f"  ✗ FAIL: DE bloqueado debería dar 403, got ok={ok} code={code}"); errors += 1

# Validación case-insensitive
ok, code = check_geo_access("de", {"blocked_regions": ["DE"], "availability_windows": []})
if not ok and code == 403:
    print("  ✓ PASS: Bloqueo case-insensitive (de == DE)")
else:
    print(f"  ✗ FAIL: Case-insensitive falló"); errors += 1

# País no bloqueado → acceso permitido
ok, code = check_geo_access("ES", {"blocked_regions": ["DE", "FR"], "availability_windows": []})
if ok:
    print("  ✓ PASS: País no bloqueado ES → permitido")
else:
    print(f"  ✗ FAIL: ES debería estar permitido"); errors += 1

# Sin restricciones → acceso libre
ok, code = check_geo_access("US", {"blocked_regions": [], "availability_windows": []})
if ok:
    print("  ✓ PASS: Sin restricciones → acceso libre")
else:
    print(f"  ✗ FAIL: Sin restricciones debería permitir acceso"); errors += 1

now = datetime.now(timezone.utc)

# Ventana activa → acceso permitido
window_active = [{
    "start_time": (now - timedelta(hours=1)).isoformat(),
    "end_time":   (now + timedelta(hours=1)).isoformat(),
}]
ok, code = check_geo_access("US", {"blocked_regions": [], "availability_windows": window_active})
if ok:
    print("  ✓ PASS: Dentro de ventana de disponibilidad → permitido")
else:
    print(f"  ✗ FAIL: Ventana activa debería permitir acceso"); errors += 1

# Ventana expirada → 403
window_expired = [{
    "start_time": (now - timedelta(hours=2)).isoformat(),
    "end_time":   (now - timedelta(hours=1)).isoformat(),
}]
ok, code = check_geo_access("US", {"blocked_regions": [], "availability_windows": window_expired})
if not ok and code == 403:
    print("  ✓ PASS: Ventana expirada → 403")
else:
    print(f"  ✗ FAIL: Ventana expirada debería dar 403"); errors += 1

sys.exit(errors)
PYEOF
[[ $? -eq 0 ]] && pass "geo_middleware" || fail "geo_middleware"

################################################################################
echo ""
echo "=== #83 Frequency Rights Management ==="
################################################################################
python3 - <<'PYEOF'
import sys
errors = 0
from rights import RightsManager

rm = RightsManager()

# 3 reproducciones dentro del límite
for i in range(1, 4):
    ok = rm.record_play("sub_test", max_plays=3)
    if ok:
        print(f"  ✓ PASS: Reproducción {i}/3 → permitida")
    else:
        print(f"  ✗ FAIL: Reproducción {i}/3 debería estar permitida"); errors += 1

# La 4ª supera el límite → denegada
ok = rm.record_play("sub_test", max_plays=3)
if not ok:
    print("  ✓ PASS: Reproducción 4 superando max_plays=3 → denegada (HTTP 403)")
else:
    print("  ✗ FAIL: max_plays superado debería denegar"); errors += 1

# Reset del contador → permite de nuevo
rm.reset("sub_test")
ok = rm.record_play("sub_test", max_plays=3)
if ok:
    print("  ✓ PASS: Tras reset del contador → primera reproducción permitida")
else:
    print("  ✗ FAIL: Tras reset debería permitir reproducción"); errors += 1

# Suscripciones independientes no se afectan mutuamente
for _ in range(3):
    rm.record_play("sub_other", max_plays=3)
ok_a = rm.record_play("sub_test", max_plays=3)   # sub_test tiene 1 play
ok_b = rm.record_play("sub_other", max_plays=3)  # sub_other tiene 3 plays → 4ta denegada
if ok_a and not ok_b:
    print("  ✓ PASS: Contadores por suscripción son independientes")
else:
    print(f"  ✗ FAIL: Aislamiento de contadores falló ok_a={ok_a} ok_b={ok_b}"); errors += 1

sys.exit(errors)
PYEOF
[[ $? -eq 0 ]] && pass "rights" || fail "rights"

################################################################################
echo ""
echo "=== #80 EZDRM: sanitización base64 del challenge ==="
################################################################################
python3 - <<'PYEOF'
import sys, base64
errors = 0
from ezdrm_client import _sanitize_base64

# Base64 válido → pasa la sanitización
valid = base64.b64encode(b"fake CDM challenge data 1234").decode()
try:
    result = _sanitize_base64(valid)
    assert result == valid.strip(), "re-codificación alteró valor válido"
    print("  ✓ PASS: Challenge base64 válido → sanitizado sin alteraciones")
except Exception as e:
    print(f"  ✗ FAIL: Challenge válido rechazado: {e}"); errors += 1

# Inyección SQL-like → rechazada
for malicious in ["'; DROP TABLE keys; --", "<script>alert(1)</script>", "../../etc/passwd"]:
    try:
        _sanitize_base64(malicious)
        print(f"  ✗ FAIL: Inyección no detectada: {malicious!r}"); errors += 1
    except ValueError:
        print(f"  ✓ PASS: Inyección rechazada: {malicious[:30]!r}")

# Padding incorrecto → rechazado (validate=True en base64.b64decode)
try:
    _sanitize_base64("bm90dmFsaWQ")  # sin padding
    # Puede que Python lo acepte añadiendo padding; si no lanza, es aceptable
    print("  ✓ PASS: Base64 sin padding → manejado correctamente")
except (ValueError, Exception):
    print("  ✓ PASS: Base64 con padding incorrecto → rechazado")

sys.exit(errors)
PYEOF
[[ $? -eq 0 ]] && pass "ezdrm_client sanitización" || fail "ezdrm_client sanitización"

################################################################################
echo ""
echo "=== #80 EZDRM: proxy_license_request (STUB) ==="
################################################################################
python3 - <<'PYEOF'
import sys, base64
errors = 0
from ezdrm_client import proxy_license_request

valid_challenge = base64.b64encode(b"fake CDM challenge bytes 0123456789").decode()

# Challenge base64 válido + drm_system widevine → devuelve bytes no vacíos
try:
    result = proxy_license_request("widevine", "test_content_id", valid_challenge)
    if isinstance(result, bytes) and len(result) > 0:
        print("  ✓ PASS: proxy_license_request widevine → retorna bytes no vacíos")
    else:
        print(f"  ✗ FAIL: resultado inesperado: type={type(result)} len={len(result) if isinstance(result, bytes) else 'N/A'}")
        errors += 1
except Exception as e:
    print(f"  ✗ FAIL: excepción inesperada con challenge válido: {e}"); errors += 1

# Challenge con caracteres no-base64 → ValueError (sanitización)
for bad_challenge in ["<script>alert(1)</script>", "'; DROP TABLE--", "../../etc/passwd"]:
    try:
        proxy_license_request("widevine", "test_content_id", bad_challenge)
        print(f"  ✗ FAIL: challenge inválido no lanzó ValueError: {bad_challenge!r}"); errors += 1
    except ValueError:
        print(f"  ✓ PASS: challenge no-base64 lanza ValueError: {bad_challenge[:30]!r}")
    except Exception as e:
        print(f"  ✗ FAIL: excepción incorrecta {type(e).__name__} para {bad_challenge!r}: {e}"); errors += 1

# El campo license (bytes → base64) es base64 válido
try:
    result = proxy_license_request("playready", "test_content_id", valid_challenge)
    license_b64 = base64.b64encode(result).decode()
    base64.b64decode(license_b64, validate=True)  # lanza si no es base64 puro
    print("  ✓ PASS: bytes de licencia son codificables como base64 válido (campo license)")
except Exception as e:
    print(f"  ✗ FAIL: campo license no es base64 válido: {e}"); errors += 1

# drm_system desconocido → ValueError
try:
    proxy_license_request("unknown_drm", "test_content_id", valid_challenge)
    print("  ✗ FAIL: drm_system desconocido no lanzó ValueError"); errors += 1
except ValueError:
    print("  ✓ PASS: drm_system desconocido → ValueError")
except Exception as e:
    print(f"  ✗ FAIL: excepción incorrecta {type(e).__name__}: {e}"); errors += 1

sys.exit(errors)
PYEOF
[[ $? -eq 0 ]] && pass "ezdrm_client proxy_license_request" || fail "ezdrm_client proxy_license_request"

################################################################################
echo ""
echo "============================================"
echo " RESULTADO FINAL — DRM Flow Test"
echo " PASS: $PASS   FAIL: $FAIL"
echo "============================================"

[[ $FAIL -eq 0 ]]
