# qos/

Métricas de Quality of Service y observabilidad de la plataforma: latencia glass-to-glass, jitter, rebuffering, ABR steady-state.

- **Agente responsable**: [Sync & Telemetry](../.github/agents/sync-telemetry.agent.md).
- **Contratos**: [schemas/sync/](../schemas/sync/).
- **Regla**: exportación en formato Prometheus/OpenMetrics; las métricas de negocio (revenue) viven en `comercial/`.

## Estado

Fase 0 · stub. Validación inicial en issue [#58](https://github.com/jimbomilk/teremoqwow/issues/58).
