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
| MSF draft-01 (catálogo, track, perfil teremoqwow) | [schemas/moq/msf/v1/](../schemas/moq/msf/v1/) | Arquitecto |
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

## Perfil MSF (draft-ietf-moq-msf-01) — `schemas/moq/msf/v1/`

Contrato **aditivo**: no sustituye ni modifica `schemas/media/v2/catalog.json` (catálogo Hang, el que hoy producen y consumen relay y player) ni `schemas/media/v1/catalog.json` (deprecated). Ningún productor ni consumidor emite aún este catálogo; sólo existe el contrato. Integración con QoS CHECK 3 (broadcast hermano `${BROADCAST}-meta`, flag `QOS_MSF_CATALOG`, veredicto `CATALOG_ERROR`): [02-DOCS/wiki/ftd/qos-msf-catalog-check3.md](../02-DOCS/wiki/ftd/qos-msf-catalog-check3.md).

| Fichero | Contenido |
|---|---|
| `catalog.json` | Catálogo MSF independiente, `version` fijada a `"draft-01"`, publicado en el track estándar `catalog`. `deltaUpdate` fuera de alcance. |
| `track.json` | Objeto track MSF §5.2. `packaging`: valores del draft o extensión `x-*`. |
| `teremoqwow-extension.json` | Clave `teremoqwow` del track: `container` (legacy/cmaf), `representation`, `schema`. |
| `teremoqwow-profile.json` | Perfil: catálogo MSF + tracks `video`, `audio`, `telemetry` actuales. |
| `examples/{valid,invalid}/` | Instancias de contrato (18 negativas, una violación cada una). |

Decisiones y límites honestos:

- **Sin `packaging=loc`**: la media actual va en contenedor Hang (legacy/cmaf), no LOC. Se declara `x-teremoqwow-hang` + `teremoqwow.container`. Un `x-*` no es un valor de la Tabla 3 del draft: un player MSF genérico no sabrá reproducirlo; la adopción es del envoltorio del catálogo, no del empaquetado.
- **Telemetría**: track `telemetry`, `role=telemetry` (rol propio), `packaging=x-teremoqwow-json`, `mimeType=application/json`, `timescale=90000` (`pts_90khz`), sin `codec`. `representation=json-snapshot-v1`: cada objeto MoQ es un snapshot JSON autocontenido (sin deltas) que valida contra `schemas/sync/v1/telemetry-track-event.json`, referenciado en `teremoqwow.schema`. No es un `eventtimeline` MSF.
- `catalog` es nombre reservado: ningún track de contenido puede llamarse así. Unicidad `(namespace,name)` no expresable en JSON Schema; la verifica el productor.
- Derivado de `draft-ietf-moq-msf-01` (junio 2026); cualquier draft posterior requiere `v2/`.

Pruebas: `scripts/test-msf-schemas.sh`.

## Validación

Todos los esquemas se validan en CI mediante [`scripts/validate-schemas.sh`](../scripts/validate-schemas.sh) (usa `ajv-cli`).
