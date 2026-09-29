# Contratos (`schemas/`)

## Convenciones

- Draft: **JSON Schema 2020-12** (`$schema: "https://json-schema.org/draft/2020-12/schema"`).
- `$id`: URL canónica `https://teremoqwow.dev/schemas/<dominio>/<version>/<nombre>.json`.
- Versión **SemVer en el path** (`v1/`, `v2/`). Cambios breaking = nuevo directorio de versión.
- `additionalProperties: false` por defecto; excepciones justificadas en el propio esquema.
- Nombres de campo en `snake_case`; identificadores en `kebab-case`.

## Ciclo de vida

1. **Draft** → PR con esquema nuevo bajo `vN/` marcado `deprecated: false`.
2. **Stable** → tras merge, prohibido cambio breaking sobre esa versión.
3. **Deprecated** → se anota `deprecated: true` en el JSON y se abre issue de retirada.
4. **Removed** → se borra el directorio de versión sólo tras al menos una release estable con el sucesor.

## Índice por dominio

| Dominio | Ruta | Responsable |
|---|---|---|
| Común (errores, timestamps) | [schemas/common/](../schemas/common/) | Arquitecto |
| Media (renditions, catálogo MoQ) | [schemas/media/](../schemas/media/) | Media Pipeline |
| Relay MoQ (announce, subscribe) | [schemas/relay/](../schemas/relay/) | MoQ Core |
| Sincronización, telemetría, QoS, overlays | [schemas/sync/](../schemas/sync/) | Sync & Telemetry |
| DRM (licencias) | [schemas/drm/](../schemas/drm/) | Monetization & DRM |
| Registry (nodos, join) | [schemas/registry/](../schemas/registry/) | MoQ Core |
| API pública (OpenAPI KrakenD, interacciones) | [schemas/api/](../schemas/api/) | Arquitecto |

## Endpoints KrakenD (API Gateway)

Contratos de los endpoints públicos expuestos por KrakenD en `config/krakend/krakend.json`.

| Método | Path | Backend upstream | Descripción |
|---|---|---|---|
| `GET` | `/health` | moq-relay `:8090/health` | Estado del relay; devuelve `{"status":"ok"}` |
| `POST` | `/registry/join` | relay/registry_server `:8080/join` | Registro de nodo en el clúster federado |
| `POST` | `/stripe/webhook` | comercial/billing `webhook_handler.py` | Eventos Stripe (invoice, subscription) |
| `POST` | `/drm/license` | EZDRM license server | Emisión de licencia Widevine/PlayReady/FairPlay |
| `POST` | `/interactions` | sync & telemetry track | Eventos de interactividad (polls, reacciones) |

### Convenciones de respuesta

- Éxito: HTTP 200 con cuerpo JSON conforme al esquema `schemas/api/v1/`.
- Error de cliente: HTTP 400 con `{"error": "<mensaje>"}`.
- Error de servidor: HTTP 502/503 con `{"error": "upstream_error"}` — nunca exponer detalles internos.
- Autenticación: Bearer JWT en cabecera `Authorization` para todos los endpoints excepto `/health`.

## Validación

Todos los esquemas se validan en CI mediante [`scripts/validate-schemas.sh`](../scripts/validate-schemas.sh) (usa `ajv-cli`).
