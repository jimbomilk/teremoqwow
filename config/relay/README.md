# config/relay/

Configuración del relay MoQ (`moq-relay-ietf`) para teremoqwow.

- **Agente responsable**: MoQ Core
- **Issue**: [#54 — Fase 0: Configurar moq-relay-ietf Base](https://github.com/jimbomilk/teremoqwow/issues/54)
- **Contratos**: [schemas/relay/v1/announce.json](../../schemas/relay/v1/announce.json) · [schemas/relay/v1/subscribe.json](../../schemas/relay/v1/subscribe.json)

---

## Archivos

| Archivo | Descripción |
|---------|-------------|
| `relay.toml` | Configuración principal del relay (bind, TLS, auth, log) |
| `certs/` | Directorio para certificados dev (ver `certs/README.md`) |

---

## Arrancar el relay

No existe imagen Docker oficial publicada para `moq-relay-ietf` en este momento.
El binario se compilará desde el workspace `relay/` en fases posteriores (Rust / crate `moq-rs`).

### Con `cargo run` (desarrollo)

```bash
# Desde la raíz del repo, una vez que relay/ tenga el Cargo.toml
cargo run --manifest-path relay/Cargo.toml -- \
  --config config/relay/relay.toml
```

> **Puerto 443**: en Linux, los puertos < 1024 requieren `CAP_NET_BIND_SERVICE` o root.
> Para evitarlo en dev, cambia `bind = ":443"` a `bind = ":4443"` en `relay.toml`.

### Con Docker (cuando exista imagen local)

```bash
# Construir imagen local desde relay/
docker build -t teremoqwow/moq-relay:dev relay/

# Arrancar con la config montada
docker run --rm -it \
  -p 4443:4443 \
  -p 9101:9101 \
  -v "$(pwd)/config/relay:/etc/moq-relay:ro" \
  teremoqwow/moq-relay:dev \
  --config /etc/moq-relay/relay.toml
```

---

## Generar certificados TLS (paso previo obligatorio)

Los certificados **no están en el repo**. Genera los archivos locales con:

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

Ver instrucciones completas (incluyendo `public.jwk`) en [certs/README.md](certs/README.md).

---

## Verificar el health endpoint

Una vez el relay esté en marcha, verifica que responde:

```bash
curl -k https://127.0.0.1:9101/health
```

Respuesta esperada: HTTP `200 OK` con body `ok` o JSON `{"status":"ok"}`.

> `-k` omite la verificación del certificado autofirmado. No usar en producción.

---

## Ejemplo de publicación y suscripción

> Comandos de referencia con `moq-clock` (incluido en `moq-rs`). No se ejecutan solos sin el relay activo.

**Publicar un namespace** (producer):

```bash
moq-clock --tls-disable-verify \
  --url "https://localhost:4443" \
  --namespace "teremoqwow/dev/stream1" \
  publish
```

**Suscribirse a un track** (consumer):

```bash
moq-clock --tls-disable-verify \
  --url "https://localhost:4443" \
  --namespace "teremoqwow/dev/stream1" \
  --track "video" \
  subscribe
```

El campo `auth_token` del announce sigue el esquema [schemas/relay/v1/announce.json](../../schemas/relay/v1/announce.json).
El campo `priority` del subscribe sigue el esquema [schemas/relay/v1/subscribe.json](../../schemas/relay/v1/subscribe.json).
