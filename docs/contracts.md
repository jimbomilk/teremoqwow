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
| Media (renditions, catálogo) | [schemas/media/](../schemas/media/) | Media Pipeline |
| Relay MoQ (announce, subscribe) | [schemas/relay/](../schemas/relay/) | MoQ Core |
| Sincronización y telemetría | [schemas/sync/](../schemas/sync/) | Sync & Telemetry |
| DRM (licencias) | [schemas/drm/](../schemas/drm/) | Monetization & DRM |
| Registry (nodos de federación) | [schemas/registry/](../schemas/registry/) | MoQ Core |
| API pública (OpenAPI KrakenD) | [schemas/api/](../schemas/api/) | Arquitecto |

## Validación

Todos los esquemas se validan en CI mediante [`scripts/validate-schemas.sh`](../scripts/validate-schemas.sh) (usa `ajv-cli`).
