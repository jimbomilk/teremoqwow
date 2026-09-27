# schemas/

Contratos de `teremoqwow` como fuente única de verdad.

Ver [docs/contracts.md](../docs/contracts.md) para convenciones completas (draft, `$id`, versionado SemVer, ciclo de vida).

## Estructura

| Dominio | Ruta | Propietario |
|---|---|---|
| Común | [common/](common/) | Arquitecto |
| Media | [media/](media/) | Media Pipeline |
| Relay MoQ | [relay/](relay/) | MoQ Core |
| Sync + Telemetría | [sync/](sync/) | Sync & Telemetry |
| DRM | [drm/](drm/) | Monetization & DRM |
| Registry de nodos | [registry/](registry/) | MoQ Core |
| API pública | [api/](api/) | Arquitecto |

## Validación

CI ejecuta [`scripts/validate-schemas.sh`](../scripts/validate-schemas.sh) en cada PR.
