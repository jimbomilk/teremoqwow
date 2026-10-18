# schemas/

Contratos de `teremoqwow` como fuente única de verdad.

Ver [docs/contracts.md](../docs/contracts.md) para convenciones completas (draft, `$id`, versionado SemVer, ciclo de vida).

## Estructura

| Dominio | Ruta | Propietario |
|---|---|---|
| Común | [common/](common/) | Arquitecto |
| Media | [media/](media/) | Media Pipeline |
| MSF (draft-ietf-moq-msf-01) | [moq/msf/v1/](moq/msf/v1/) | Arquitecto |
| Relay MoQ | [relay/](relay/) | MoQ Core |
| Sync + Telemetría | [sync/](sync/) | Sync & Telemetry |
| DRM | [drm/](drm/) | Monetization & DRM |
| Registry de nodos | [registry/](registry/) | MoQ Core |
| API pública | [api/](api/) | Arquitecto |

## Validación

CI ejecuta [`scripts/validate-schemas.sh`](../scripts/validate-schemas.sh) en cada PR. Los ficheros bajo `*/examples/` son instancias, no schemas, y se excluyen de esa compilación.

Pruebas del perfil MSF (ejemplos válidos aceptados / inválidos rechazados): [`scripts/test-msf-schemas.sh`](../scripts/test-msf-schemas.sh).
