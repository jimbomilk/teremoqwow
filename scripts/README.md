# scripts/

Utilidades del monorepo.

| Script | Propósito | Precondiciones |
|---|---|---|
| [validate-schemas.sh](validate-schemas.sh) | Valida todos los `schemas/**/*.json` con AJV (JSON Schema 2020-12) | `npx ajv-cli` |
| [apply-ruleset.sh](apply-ruleset.sh) | Aplica los rulesets declarados en `.github/rulesets/*.json` de forma idempotente | `gh` autenticado con permiso admin en el repo |
| [sync-labels.sh](sync-labels.sh) | Sincroniza las labels con `.github/labels.yml` | `gh` autenticado, `yq` |

Todos los scripts asumen ejecución desde la raíz del repo.
