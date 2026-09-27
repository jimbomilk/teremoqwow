# .github/rulesets/

Rulesets de rama versionados como **Infrastructure-as-Code**. Fuente de verdad de la protección de ramas.

## Ficheros

| Fichero | Aplica a | Descripción |
|---|---|---|
| [main-protection.json](main-protection.json) | `refs/heads/main` | PR obligatorio con revisión de CODEOWNER, checks de CI y CodeQL, historia lineal, sin force-push ni delete. Bypass sólo para `Repository admin`. |

## Aplicación

Los rulesets se aplican con [`scripts/apply-ruleset.sh`](../../scripts/apply-ruleset.sh) (idempotente: crea si no existe, actualiza si ya está por `name`).

```bash
# Aplicar todos los rulesets del directorio
./scripts/apply-ruleset.sh

# Aplicar uno concreto
./scripts/apply-ruleset.sh main-protection
```

Requiere `gh` autenticado con permiso admin sobre el repo.

## Notas

- Los `bypass_actors[].actor_id` para roles predefinidos son:
  - `Repository admin` → `5`
  - `Maintain` → `4`
  - `Write` → `2`
- Los `required_status_checks.context` deben coincidir exactamente con los nombres de job en los workflows.
