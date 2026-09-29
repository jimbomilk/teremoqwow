# Roadmap

## Fase 0 — Fundación (milestone [`Fase 0: Fundacion`](https://github.com/jimbomilk/teremoqwow/milestones/1))

| Issue | Entregable |
|---|---|
| [#50](https://github.com/jimbomilk/teremoqwow/issues/50) | Monorepo + estructura base + gobernanza |
| [#51](https://github.com/jimbomilk/teremoqwow/issues/51) | Esquemas JSON base |
| [#52](https://github.com/jimbomilk/teremoqwow/issues/52) | MediaMTX ingesta SRT |
| [#53](https://github.com/jimbomilk/teremoqwow/issues/53) | SRT Bonding |
| [#54](https://github.com/jimbomilk/teremoqwow/issues/54) | moq-relay-ietf base |
| [#55](https://github.com/jimbomilk/teremoqwow/issues/55) | KrakenD API Gateway base |
| [#56](https://github.com/jimbomilk/teremoqwow/issues/56) | Transcodificación moq-mux |
| [#57](https://github.com/jimbomilk/teremoqwow/issues/57) | Player básico @moq/watch |
| [#58](https://github.com/jimbomilk/teremoqwow/issues/58) | Validación latencia glass-to-glass |

## Fase 1 — Multicalidad (milestone [`Fase 1: Multicalidad`](https://github.com/jimbomilk/teremoqwow/milestones/2)) ✅

| Issue | Entregable |
|---|---|
| [#59](https://github.com/jimbomilk/teremoqwow/issues/59) | DTS en moq-relay |
| [#60](https://github.com/jimbomilk/teremoqwow/issues/60) | ABR client-side |
| [#61](https://github.com/jimbomilk/teremoqwow/issues/61) | Test switching sin artefactos |
| [#62](https://github.com/jimbomilk/teremoqwow/issues/62) | Keyframes y SPS/PPS alineados |
| [#116](https://github.com/jimbomilk/teremoqwow/issues/116) | Alineación upstream moq-rs 0.15/0.12 |

## Fase 2 — Audio + Sync (milestone [`Fase 2: Audio + Sync`](https://github.com/jimbomilk/teremoqwow/milestones/3)) ✅

| Issue | Entregable |
|---|---|
| [#63](https://github.com/jimbomilk/teremoqwow/issues/63) | Audio EBU R128 |
| [#64](https://github.com/jimbomilk/teremoqwow/issues/64) | Pistas audio multi-idioma |
| [#65](https://github.com/jimbomilk/teremoqwow/issues/65) | Track de sincronización |
| [#66](https://github.com/jimbomilk/teremoqwow/issues/66) | Verificador lip-sync |
| [#67](https://github.com/jimbomilk/teremoqwow/issues/67) | Subtítulos WVTT |
| [#68](https://github.com/jimbomilk/teremoqwow/issues/68) | Subtítulos STPP |
| [#69](https://github.com/jimbomilk/teremoqwow/issues/69) | Sign language y audiodescripción |

## Fase 3 — Telemetría (milestone [`Fase 3: Telemetria`](https://github.com/jimbomilk/teremoqwow/milestones/4)) ✅

| Issue | Entregable |
|---|---|
| [#70](https://github.com/jimbomilk/teremoqwow/issues/70) | Adaptador de telemetría (Opta/Stats Perform) |
| [#71](https://github.com/jimbomilk/teremoqwow/issues/71) | Persistencia en ClickHouse |
| [#72](https://github.com/jimbomilk/teremoqwow/issues/72) | Verificación PTS telemetría-vídeo |
| [#73](https://github.com/jimbomilk/teremoqwow/issues/73) | Prometheus scraping |
| [#74](https://github.com/jimbomilk/teremoqwow/issues/74) | Dashboards Grafana |

## Fase 4 — Interactividad (milestone [`Fase 4: Interactividad`](https://github.com/jimbomilk/teremoqwow/milestones/5)) ✅ (PR [#131](https://github.com/jimbomilk/teremoqwow/pull/131))

| Issue | Entregable |
|---|---|
| [#75](https://github.com/jimbomilk/teremoqwow/issues/75) | Sandbox de overlay (iframe allow-scripts) |
| [#76](https://github.com/jimbomilk/teremoqwow/issues/76) | Integración editor OpenOverlay |
| [#77](https://github.com/jimbomilk/teremoqwow/issues/77) | Sincronización overlay con PTS |
| [#78](https://github.com/jimbomilk/teremoqwow/issues/78) | Track de interacción (poll_open/close/stats) |

## Fase 5 — DRM + Monetización (milestone [`Fase 5: DRM + Monetizacion`](https://github.com/jimbomilk/teremoqwow/milestones/6))

| Issue | Entregable |
|---|---|
| [#79](https://github.com/jimbomilk/teremoqwow/issues/79) | Stripe Billing + webhooks + JWT |
| [#80](https://github.com/jimbomilk/teremoqwow/issues/80) | EZDRM CPIX multi-DRM (Widevine, FairPlay, PlayReady) |
| [#81](https://github.com/jimbomilk/teremoqwow/issues/81) | Test flujo pago end-to-end |
| [#82](https://github.com/jimbomilk/teremoqwow/issues/82) | Geobloqueo + ventanas de licencia |
| [#83](https://github.com/jimbomilk/teremoqwow/issues/83) | Frequency Rights Management |
| [#84](https://github.com/jimbomilk/teremoqwow/issues/84) | SSAI publicidad (Red5 + MediaTailor) |
| [#85](https://github.com/jimbomilk/teremoqwow/issues/85) | Test DRM con EME (Widevine + FairPlay) |

## Fase 6 — Federación y escala

| Issue | Entregable |
|---|---|
| [#86](https://github.com/jimbomilk/teremoqwow/issues/86) | Clustering moq-rs |
| [#87](https://github.com/jimbomilk/teremoqwow/issues/87) | Endpoint /registry/join |
| [#88](https://github.com/jimbomilk/teremoqwow/issues/88) | Nodo externo federado |
| [#89](https://github.com/jimbomilk/teremoqwow/issues/89) | Broadcast gateway SDI/NDI |
| [#90](https://github.com/jimbomilk/teremoqwow/issues/90) | MOCHA Identity |

## Fase 7 — Producción

| Issue | Entregable |
|---|---|
| [#91](https://github.com/jimbomilk/teremoqwow/issues/91) | QoS y alertas Prometheus |
| [#92](https://github.com/jimbomilk/teremoqwow/issues/92) | SLOs y SLA |
| [#93](https://github.com/jimbomilk/teremoqwow/issues/93) | Site24x7 + PagerDuty |
| [#94](https://github.com/jimbomilk/teremoqwow/issues/94) | Stripe Customer Portal |
| [#95](https://github.com/jimbomilk/teremoqwow/issues/95) | Moesif Developer Portal |
| [#96](https://github.com/jimbomilk/teremoqwow/issues/96) | Auditoría de seguridad final |
| [#97](https://github.com/jimbomilk/teremoqwow/issues/97) | Documentación completa |
| [#98](https://github.com/jimbomilk/teremoqwow/issues/98) | Plan de respuesta a incidentes |
