# config/relay/certs/

Directorio de certificados y claves para el relay MoQ en desarrollo local.

> **Nunca commitees archivos `.pem`, `.key` ni `.jwk` reales.**
> El `.gitignore` local los excluye. Solo existen en tu máquina.

---

## 1. Certificado TLS autofirmado (`relay.pem` + `relay.key`)

Ejecuta desde la raíz del repo (o desde este directorio ajustando la ruta de salida):

```bash
openssl req -x509 \
  -newkey ec -pkeyopt ec_paramgen_curve:P-256 \
  -keyout config/relay/certs/relay.key \
  -out    config/relay/certs/relay.pem \
  -days 365 \
  -nodes \
  -subj "/CN=localhost" \
  -addext "subjectAltName=DNS:localhost,IP:127.0.0.1"
```

| Parámetro | Propósito |
|-----------|-----------|
| `-newkey ec -pkeyopt ec_paramgen_curve:P-256` | Clave EC P-256, preferida para QUIC/MoQ |
| `-nodes` | Sin passphrase (el relay la necesita en disco sin interacción) |
| `-subj "/CN=localhost"` | CN mínimo requerido |
| `-addext "subjectAltName=..."` | SAN obligatorio para browsers y clientes QUIC modernos |
| `-days 365` | Validez de un año; renueva antes de que expire |

Verifica el certificado generado:

```bash
openssl x509 -in config/relay/certs/relay.pem -noout -text | grep -A2 "Subject Alternative"
```

---

## 2. Clave pública JWKS (`public.jwk`)

El relay usa `public.jwk` para **verificar** los JWT Bearer de publishers y subscribers.
Solo necesitas la clave pública; la privada la retiene el emisor de tokens (auth service).

### Opción A — con `jose` (Node.js)

```bash
# Instala la CLI de jose si no la tienes
npm install --global jose

# Genera un par EC P-256 y exporta solo la clave pública
node -e "
const { generateKeyPair } = require('crypto');
generateKeyPair('ec', { namedCurve: 'P-256' }, (err, pub, priv) => {
  if (err) throw err;
  console.log(JSON.stringify(pub.export({ format: 'jwk' }), null, 2));
});
" > config/relay/certs/public.jwk
```

### Opción B — con Python (`cryptography`)

```bash
python3 - <<'EOF'
import json
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

key = ec.generate_private_key(ec.SECP256R1())
pub = key.public_key()
nums = pub.public_numbers()

import base64, struct

def b64url(n):
    length = (n.bit_length() + 7) // 8
    return base64.urlsafe_b64encode(n.to_bytes(length, 'big')).rstrip(b'=').decode()

jwk = {"kty": "EC", "crv": "P-256", "use": "sig", "x": b64url(nums.x), "y": b64url(nums.y)}
print(json.dumps(jwk, indent=2))
EOF
> config/relay/certs/public.jwk
```

> En producción, `public.jwk` lo provee el servicio de autenticación (e.g., Keycloak, Auth0).
> Para dev, cualquier par EC P-256 válido sirve para arrancar el relay.

---

## Archivos esperados

```
config/relay/certs/
├── .gitignore   # excluye *.pem, *.key, *.jwk
├── .gitkeep     # versiona el directorio vacío
├── README.md    # este archivo
├── relay.pem    # ← generado localmente, NO commiteado
├── relay.key    # ← generado localmente, NO commiteado
└── public.jwk   # ← generado localmente, NO commiteado
```
