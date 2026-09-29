# SLA — teremoqwow Fase 7

## SLOs

| Indicador | Objetivo | Ventana de medición |
|---|---|---|
| Disponibilidad | ≥ 99.99 % | Mensual (calendar month) |
| Latencia E2E (P95) | < 700 ms | 5 min rolling |
| Tasa de error HTTP 5xx | < 0.1 % de requests | Hora rolling |
| Lip-sync audio/video | < 45 ms | Por segmento (2 s) |
| Recuperación de relay caído (RTO) | < 60 s | Por incidente |

## Definiciones

- **Disponibilidad**: % de ventanas de 1 min en que al menos un relay sirve el track primario.
- **P95 latencia E2E**: medida desde ingesta SRT hasta primer frame decodificado en player (TTFF).
- **Tasa de error**: respuestas HTTP 500–599 / total requests al gateway KrakenD.
- **Lip-sync**: diferencia entre PTS de audio y vídeo en el player medida por `verify-lipsync.sh`.

## Penalizaciones (crédito de servicio)

| Disponibilidad mensual | Crédito |
|---|---|
| 99.98 % – < 99.99 % | 5 % |
| 99.9 % – < 99.98 % | 10 % |
| 99 % – < 99.9 % | 20 % |
| < 99 % | 30 % |

Fórmula de referencia: por cada 0.01 % de disponibilidad perdida por debajo del SLO (99.99 %)
se aplica un crédito del **10 %** sobre la cuota mensual proporcional al período afectado,
hasta el máximo de la tabla anterior.

## Exclusiones

- Ventanas de mantenimiento planificado (≤ 4 h/mes, notificadas con ≥ 48 h de antelación).
- Incidentes causados por el ISP del cliente o por fuerza mayor.
- Degradación limitada a regiones fuera del contrato activo.

## Referencias

- Runbooks: [relay-down](runbooks/relay-down.md), [drm-failure](runbooks/drm-failure.md), [latency-degradation](runbooks/latency-degradation.md)
- Panel de telemetría: Grafana → dashboard `teremoqwow-e2e`
- Alertas: [config/monitoring/site24x7.yaml](../config/monitoring/site24x7.yaml)
