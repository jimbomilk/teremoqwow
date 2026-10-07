# Selección de modelos de agentes

## Intención

Reducir el coste de los agentes activos sin perder calidad de revisión. Se asigna capacidad según el volumen de tokens de cada rol y el coste de que falle.

## Alcance

Agentes activos en `.github/agents/`. Los de `_legacy/` quedan fuera.

## Tarifas (USD por 1M tokens, entrada / entrada en caché / salida)

Fuente: GitHub Docs, «Models and pricing» de Copilot, consultado el 2026-10-07.

| Modelo | Entrada | En caché | Salida |
|---|---|---|---|
| `claude-sonnet-5.5` | 2.00 | 0.20 | 10.00 |
| `gpt-6.1-sol` | 2.00 | 0.10 | 10.00 |
| `claude-haiku-4.5` | 1.00 | 0.10 | 5.00 |
| `mai-code-1.1-flash` | 0.20 | 0.02 | 1.20 |
| `gpt-6-luna` | 0.10 | 0.01 | 0.50 |

`gpt-4o-mini` no figura en la lista de modelos ni en las tarifas.

## Asignación

| Agente | Antes | Ahora | Criterio |
|---|---|---|---|
| Arquitecto | `claude-sonnet-5.5` | `claude-sonnet-5.5` | Contratos y decisión de merge; un error aquí es caro |
| developer | `claude-sonnet-5.5` | `claude-haiku-4.5` | Mayor volumen de tokens; mitad de precio; lo respaldan tests, 3 refuters y el Arquitecto |
| refuter-correctness | `claude-sonnet-5.5` | `gpt-6.1-sol` | Mismo precio, caché a la mitad; otra familia que el developer |
| refuter-security | `claude-sonnet-5.5` | `claude-sonnet-5.5` | Solo auditoría final (no por task); sin cambio de modelo |
| refuter-tests | `gpt-4o-mini` (no disponible) | `gpt-6.1-sol` | Ejecuta mutantes y ha encontrado los defectos más graves; se corrige un identificador inválido |
| deployment | `claude-haiku-4.5` | `claude-haiku-4.5` | Operaciones de producción; sin cambio |
| scout | `claude-haiku-4-5` (mal escrito) | `gpt-6-luna` | Clasificación trivial; unas 10 veces más barato |

## Checklist

- [x] Obtener tarifas reales.
- [x] Corregir identificadores inválidos (`gpt-4o-mini`, `claude-haiku-4-5`).
- [x] Actualizar las tablas del scout.
- [ ] Medir el efecto con un ciclo real (ver «Siguiente paso»).

## Evidencia

- El runtime y las tarifas listan estos modelos; no listan `gpt-4o-mini`.
- No hay benchmarks propios: la eficiencia con el developer más barato no está medida.
- En el ciclo QoS de 2026-10-05 los refuters encontraron un CRITICAL y varios HIGH tras cada ronda del developer. Por eso los revisores no se abaratan.

## Siguiente paso

Usar la nueva asignación en el siguiente ciclo y revertir el developer a `claude-sonnet-5.5` si se necesitan más de 2 rondas por tarea o si los refuters encuentran más HIGH/CRITICAL que antes.
