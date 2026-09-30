# Runbook: Fallo DRM (EZDRM)

**Severidad**: P1 (contenido protegido inaccesible)  
**SLO afectado**: Disponibilidad, tasa de error  
**RTO objetivo**: < 120 s

## Síntomas

- Players con error `EME: key status expired/output-restricted`.
- Respuestas HTTP 5xx en `/drm/license` (KrakenD → EZDRM upstream).
- Alertas Site24x7 en endpoint `/drm/license`.

## Diagnóstico rápido

```bash
# 1. Probar licencia manualmente (sustituir TOKEN por un JWT de prueba)
curl -sf -X POST https://api.teremoqwow.dev/drm/license \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"key_id":"test"}' | jq .

# 2. Verificar estado de EZDRM
curl -sf https://status.ezdrm.com/ | head -20

# 3. Revisar configuración CPIX
cat drm/cpix-config.xml | grep -i '<ContentKey'
```

## Pasos de recuperación

1. **Error 5xx del upstream EZDRM**:
   - Comprobar [https://status.ezdrm.com](https://status.ezdrm.com).
   - Si incidente en EZDRM: informar a usuarios, activar modo de gracia (ventana de licencia extendida si el proveedor lo permite).

2. **Error de credenciales** (`401 Unauthorized` hacia EZDRM):
   - Rotar credenciales: actualizar `EZDRM_API_KEY` en el vault/secret del entorno.
   - Recargar KrakenD sin downtime: `docker kill -s HUP krakend` (si soportado) o rolling restart.

3. **CPIX mal configurado**:
   - Revisar `drm/cpix-config.xml` contra el esquema `schemas/drm/v1/`.
   - Corregir, commitear en rama y desplegar tras revisión del Arquitecto.

4. **Cache de licencias corrompida**:
   - Limpiar cache en KrakenD (reinicio del pod/contenedor).
   - Verificar que el TTL de cache en `config/krakend/krakend.json` sea ≤ duración de licencia.

## Escalado

- > 2 min sin resolución → escalar a on-call.
- Incidente externo confirmado en EZDRM → abrir canal de comunicación con clientes.

## Post-mortem

Documentar en `docs/adr/` si el fallo expone un gap de resiliencia (p. ej. falta de proveedor DRM secundario).
