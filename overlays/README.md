# overlays/

Overlays HTML5 interactivos sincronizados con el vídeo (marcadores, estadísticas, publicidad no intrusiva).

- **Agente responsable**: [Player & Overlay](../.github/agents/player-overlay.agent.md).
- **Contratos**: [schemas/sync/](../schemas/sync/) (frames de telemetría con PTS).
- **Boundary**: los overlays leen el bus de sincronización del player; no acceden directamente a red externa.

## Estado

Fase 0 · stub. Implementación distribuida entre Fase 1 y Fase 3.
