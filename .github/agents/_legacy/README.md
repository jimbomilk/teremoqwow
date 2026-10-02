# Agentes legacy — documentación de dominio archivada

A partir del 2026-10-02, el desarrollo de `teremoqwow` **no se delega a estos
agentes**. Todo el trabajo de implementación pasa por `developer.agent.md`.

Estos ficheros se conservan únicamente como **documentación del conocimiento
específico** de cada dominio (directorios que toca, invariantes del dominio,
reglas de validación). El `developer` referencia esta información a través de la
matriz de dominios incluida en `developer.agent.md`.

## Flujo actual

```
Arquitecto (contratos, schemas)
    ▼
developer (TDD RED→GREEN→REFACTOR en el dominio correspondiente)
    ▼
refuter-correctness + refuter-security + refuter-tests  (en paralelo)
    ▼
Arquitecto (merge, vincula al proyecto GitHub #3)
```

## Agentes archivados

| Dominio | Fichero original |
|---|---|
| Media (SRT, FFmpeg, MediaMTX, moq-mux, SDI/NDI) | `media-pipeline.agent.md` |
| Relay MoQ, DTS, federación, clustering | `moq-core.agent.md` |
| Player @moq/watch, ABR, overlays HTML5 | `player-overlay.agent.md` |
| Sync lip-sync, telemetry track, Prometheus/Grafana | `sync-telemetry.agent.md` |
| Opta/Stats Perform/GeoIP, Frequency Rights | `data-adapters.agent.md` |
| Stripe Billing, EZDRM, SSAI | `monetization-drm.agent.md` |
| Stripe Portal, Moesif Developer Portal | `client-portal.agent.md` |

## Si necesitas invocarlos directamente

No lo hagas. Si una tarea requiere expertise de uno de estos dominios, abre un
PR a `developer.agent.md` ampliando su matriz de dominios con lo que falte.
