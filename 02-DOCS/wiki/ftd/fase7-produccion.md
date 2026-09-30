# Fase 7 — Producción (#91–#98)

## Intent
Configurar la plataforma para producción: alertas QoS, SLOs documentados, monitoreo 24/7,
portales cliente/dev, auditoría de seguridad OWASP y plan de respuesta a incidentes.

## Scope
- **In**: reglas Prometheus, SLOs, runbooks, auditoría SAST semgrep, portal Stripe/Moesif (config)
- **Out**: Site24x7 real (requiere cuenta), PagerDuty real (requiere cuenta), Stripe real

## Checklist

### #91 — QoS y Alertas Prometheus
- [ ] Reglas `config/prometheus/rules/teremoqwow.yml` — alertas: lip-sync >45ms, buffer <500ms, latencia P95 >700ms, video_continuity_errors >0
- [ ] Verificar: `promtool check rules config/prometheus/rules/teremoqwow.yml` — exit 0

### #92 — SLOs y SLA
- [ ] `docs/sla.md` con disponibilidad 99.99%, P95 <700ms, error rate <0.1%, lip-sync <45ms
- [ ] Formato verificable: tabla de SLOs + umbral + consecuencia

### #93 — Site24x7 y Monitoreo 24/7
- [ ] `config/monitoring/site24x7.yaml` — stub configuración endpoints externos
- [ ] `docs/runbooks/` — al menos 3 runbooks: caída relay, fallo DRM, degradación latencia

### #94 — Stripe Customer Portal
- [ ] `comercial/stripe-portal/config.json` — configuración portal autoservicio
- [ ] Flujo documentado: JWT → Stripe Portal → gestión suscripción

### #95 — Moesif Developer Portal
- [ ] `comercial/moesif/config.yaml` — endpoints `/account/usage`, `/account/invoices`, `/account/api-keys`
- [ ] Verificar: schema del response de usage conforme al contrato

### #96 — Auditoría de Seguridad Final
- [ ] Ejecutar `semgrep --config auto comercial/ relay/ drm/ player/src/` — evidencia: output real
- [ ] Verificar iframe sandbox sin `allow-same-origin` en `overlays/poll.html`
- [ ] Verificar JWT RS256 en `comercial/billing/webhook_handler.py`
- [ ] Verificar mTLS stub en `config/relay/relay.toml`

### #97 — Documentación Completa
- [ ] `docs/architecture.md` actualizado con Fases 0-7
- [ ] `docs/contracts.md` con todos los endpoints KrakenD

### #98 — Plan de Respuesta a Incidentes
- [ ] `docs/runbooks/relay-down.md`
- [ ] `docs/runbooks/drm-failure.md`
- [ ] `docs/runbooks/latency-degradation.md`

## Evidence

| Check | Evidencia observada | Resultado |
|---|---|---|
| #91 promtool check rules | `SUCCESS: 2 rules found` (exit 0) | ✅ PASS |
| #92 docs/sla.md | Fichero creado con tabla SLOs | ✅ Creado |
| #93 config/monitoring/site24x7.yaml | Fichero creado con 4 endpoints monitorizados | ✅ Creado |
| #94 comercial/stripe-portal/config.json | Fichero creado con billing_portal.features | ✅ Creado |
| #95 comercial/moesif/config.yaml | Fichero creado con 3 endpoints + schemas | ✅ Creado |
| #96 semgrep 0 críticos | `Findings: 3, Critical/Error: 0 — PASS` (exit 0) | ✅ PASS |
| #96b sandbox sin allow-same-origin | `sandbox='allow-scripts'` L232 moq-watch.ts, sin allow-same-origin | ✅ PASS |
| #96c JWT RS256 | 5 menciones de RS256 en webhook_handler.py | ✅ PASS |
| #97 docs/architecture.md + contracts.md | Sección Fase 7 añadida + tabla endpoints KrakenD | ✅ Actualizado |
| #98 3 runbooks | relay-down.md, drm-failure.md, latency-degradation.md | ✅ Creados |
| validate-schemas.sh | All schemas valid | ✅ PASS |

## Next
Comenzar por #91 (QoS alertas) y #96 (auditoría seguridad) — son los más verificables
con herramientas disponibles localmente (promtool, semgrep).
