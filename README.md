# teremoqwow

Plataforma de broadcast de **latencia ultra baja** sobre **Media over QUIC (MoQ)**, con telemetría e interactividad sincronizadas.

## Arquitectura

```mermaid
flowchart LR
  CAM[Cámara / Encoder SRT] -->|SRT bonding| MTX[MediaMTX]
  MTX -->|RTMP/RTP| MUX[moq-mux + FFmpeg]
  MUX -->|MoQ tracks| RELAY[moq-relay-ietf]
  RELAY -->|MoQ| PLAYER[@moq/watch player]
  RELAY -.federación.-> RELAY2[moq-relay peer]
  MUX --> SYNC[Sync & Telemetry]
  SYNC --> PLAYER
  PLAYER --> OVL[Overlays HTML5]
  ADAPT[Data Adapters] --> SYNC
  KRAKEND[KrakenD API Gateway] --> RELAY
  KRAKEND --> DRM[EZDRM Multi-DRM]
  KRAKEND --> STRIPE[Stripe Billing]
```

Ver [docs/architecture.md](docs/architecture.md) para el detalle.

## Módulos

| Módulo | Directorio | Agente responsable |
|---|---|---|
| Ingesta SRT + transcodificación | [config/](config/) + `core/` | [Media Pipeline](.github/agents/media-pipeline.agent.md) |
| Relay MoQ y federación | [relay/](relay/) | [MoQ Core](.github/agents/moq-core.agent.md) |
| Player | [player/](player/) | [Player & Overlay](.github/agents/player-overlay.agent.md) |
| Overlays interactivos | [overlays/](overlays/) | [Player & Overlay](.github/agents/player-overlay.agent.md) |
| Sincronización y QoS | [core/](core/), [qos/](qos/) | [Sync & Telemetry](.github/agents/sync-telemetry.agent.md) |
| Adaptadores de datos | [adapters/](adapters/) | [Data Adapters](.github/agents/data-adapters.agent.md) |
| Monetización y DRM | [comercial/](comercial/), [drm/](drm/) | [Monetization & DRM](.github/agents/monetization-drm.agent.md) |
| Portal cliente | [comercial/](comercial/) | [Client Portal](.github/agents/client-portal.agent.md) |
| Contratos y gateway | [schemas/](schemas/), `config/krakend/` | [Arquitecto](.github/agents/arquitecto.agent.md) |

## Documentación

- [Arquitectura](docs/architecture.md)
- [Contratos (schemas)](docs/contracts.md)
- [Roadmap](docs/roadmap.md)
- [ADRs](docs/adr/)

## Estado

**Fase 0 — Fundación** (milestone [`Fase 0: Fundacion`](https://github.com/jimbomilk/teremoqwow/milestones/1)).

## Cómo contribuir

1. Discute cambios de contratos en [Discussions](https://github.com/jimbomilk/teremoqwow/discussions) antes del PR.
2. `main` está protegido: PR con revisión de CODEOWNER + checks `schema-validate` y `CodeQL` verdes + historia lineal.
3. Sigue las convenciones de [docs/contracts.md](docs/contracts.md) para cualquier nuevo esquema.

## Seguridad

Ver [SECURITY.md](SECURITY.md) para reportar vulnerabilidades.

## Licencia

[Apache License 2.0](LICENSE).
