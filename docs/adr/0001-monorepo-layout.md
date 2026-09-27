# 0001 - Layout de monorepo para `teremoqwow`

- **Estado**: Aceptado
- **Fecha**: 2026-09-27
- **Deciden**: @jimbomilk

## Contexto

`teremoqwow` integra componentes heterogéneos (Rust para relay, TypeScript para player/overlays, YAML/JSON para gateway y esquemas, scripts de orquestación) con contratos compartidos. Necesitamos una estructura que:

- Mantenga los contratos como fuente única de verdad accesible a todos los módulos.
- Permita evolución independiente por dominio pero con revisión centralizada de fronteras.
- Sea legible y navegable sin herramientas específicas.

## Decisión

Adoptamos un **monorepo por dominio** con los siguientes directorios de primer nivel:

| Directorio | Responsabilidad |
|---|---|
| `schemas/` | Contratos JSON Schema / OpenAPI versionados por dominio |
| `core/` | Lógica común reutilizable (sync, tipos) |
| `relay/` | Binario del relay MoQ (Rust) |
| `player/` | Aplicación del player @moq/watch (TypeScript) |
| `overlays/` | Componentes HTML5 interactivos |
| `adapters/` | Integraciones con APIs externas normalizadas al esquema canónico |
| `comercial/` | Stripe Billing, portales, SSAI |
| `drm/` | Integración EZDRM multi-DRM |
| `qos/` | Métricas y observabilidad |
| `config/` | Configuración declarativa por servicio + `.env.example` |
| `scripts/` | Utilidades del monorepo (validación, aplicación de rulesets, labels) |
| `docs/` | Documentación viva y ADRs |
| `.github/` | Gobernanza: agentes, workflows, rulesets, templates |

## Consecuencias

- **Positivas**: contratos centralizados, un único CODEOWNERS, CI unificado, fácil onboarding.
- **Negativas**: builds acoplados si no se aíslan bien; requiere disciplina en boundaries entre módulos.
- **Neutras**: la elección de herramientas por módulo queda libre siempre que respete los contratos.

## Alternativas consideradas

- **Multi-repo por módulo**: descartado por sobrecarga de sincronización de contratos y CI duplicado.
- **Monorepo con Nx/Turbo**: prematuro; se puede adoptar más adelante si la escala lo justifica.
