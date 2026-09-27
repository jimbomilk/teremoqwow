# core/

Lógica común reutilizable: tipos compartidos, utilidades de sincronización, helpers de catálogo MoQ.

- **Agente responsable**: [Arquitecto](../.github/agents/arquitecto.agent.md) (coordinación); consumidores: `moq-core`, `media-pipeline`, `sync-telemetry`.
- **Contratos que consume**: [schemas/common/](../schemas/common/), [schemas/media/](../schemas/media/).
- **Reglas**:
  - No conoce infraestructura (no habla con red ni con disco).
  - Cambios que afecten a tipos públicos requieren PR con revisión del Arquitecto.

## Estado

Fase 0 · stub. Se poblará en issues siguientes de Fase 1.
