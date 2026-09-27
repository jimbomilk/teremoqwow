# qos/

Métricas de Quality of Service y observabilidad de la plataforma: latencia glass-to-glass, jitter, rebuffering, ABR steady-state.

- **Agente responsable**: [Sync & Telemetry](../.github/agents/sync-telemetry.agent.md).
- **Contratos**: [schemas/sync/](../schemas/sync/).
- **Regla**: exportación en formato Prometheus/OpenMetrics; las métricas de negocio (revenue) viven en `comercial/`.

## Estructura

### Fase 0 — Validación latencia glass-to-glass

**Objetivo**: Establecer y validar el presupuesto de latencia end-to-end (capture → player render), con criterio de aceptación P95 ≤ 700ms.

**Archivos**:
- [`latency-budget.md`](./latency-budget.md): Presupuesto desagregado por etapa (ingesta, transcodificación, transporte, render) con justificación.
- [`measurement-plan.md`](./measurement-plan.md): Plan de medición usando `moq-clock-ietf` y `moq_timing_sink`; comandos end-to-end; procedimiento reproducible.
- [`scripts/measure-e2e.sh`](./scripts/measure-e2e.sh): Automatización: arranca pipeline, recoge métricas, calcula p50/p95/p99, valida vs criterio.

**Dependencias externas**:
- Player (`player/src/latency.ts`): cálculo de latencia PTS-based; emite evento `moq:latency` o persiste a fichero.
- Catálogo MoQ (desde `moq-mux`): timestamp `created_at.wallclock_ns` para sincronización NTP.
- Relay (`moq-relay-ietf`): expone track `sync` con pulsos NTP-alineados.

### Fase 1+ — Observabilidad continua

Pendiente:
- Prometheus scraping de métricas del relay y player.
- ClickHouse persistence para análisis histórico.
- Grafana dashboards de latencia (p50, p95, p99, jitter).
- Alertas basadas en reglas (e.g., "p95 > 800ms por > 5min").

## Estado

**Fase 0**: Issue [#58](https://github.com/jimbomilk/teremoqwow/issues/58) · En progreso.
