# Meta-Publisher Runbook

## Overview

`meta-publisher` es un servicio único que publica eventos sintéticos en el broadcast `anon/live1-meta`, track `heartbeat`, a cadencia ~1 Hz. Prueba SOLO llegada de datos/transporte: no afirma nada sobre calidad audiovisual.

**Fase 1 (#206):** El observador Pipeline (`ingest.data`) mide la llegada de estos eventos para verificar que la ingesta de datos está activa.

- **Imagen:** `teremoqwow-meta-track:1` (built from `ingest/meta-track/`)
- **Red:** `teremoqwow-prod` (interno)
- **Restart policy:** `unless-stopped`
- **Comunicación:** HTTP/WS a `moq-relay:8090` (sin TLS internamente)

## Startup

### Normal

```bash
docker compose -f docker-compose.prod.yml up -d meta-publisher
```

Logs (últimas líneas):

```bash
docker compose -f docker-compose.prod.yml logs -f meta-publisher | head -20
```

Esperado:
```
[Publisher] Connecting to http://moq-relay:8090/
[Publisher] Broadcast: anon/live1-meta, Track: heartbeat, Interval: 1000ms
[Publisher] Connecting (backoff: 1000ms)...
[Publisher] Connected! Starting to publish...
[Publisher] Published 60 events, boot_id=0123456789abcdef, seq=59
```

### Dependencias

- `moq-relay` debe estar arrancado y accesible en la red `teremoqwow-prod`
- Puerto HTTP 8090 del relay abierto internamente

Si el relay no está listo:
- El publisher intenta reconectar con backoff exponencial (1→5 s), hasta
  `MAX_RECONNECT_ATTEMPTS` intentos consecutivos fallidos (default **30**;
  no se define en `docker-compose.prod.yml` porque el default ES el valor de
  producción). Agotados → log `FATAL ... reconnect attempts exhausted` a
  stderr y `process.exit(1)`; `restart: unless-stopped` reinicia el servicio
  (boot_id nuevo, seq reinicia a 0 — por contrato).
- Con el default, 30 intentos × backoff ≤5 s ≈ hasta ~2,5 min sin relay antes
  del reinicio externo. Una conexión exitosa (publicación iniciada) resetea el
  contador a 0.
- Variable configurable solo para tests/diagnóstico: entero > 0; valor
  ausente o inválido (`0`, `abc`, `-2`, `2.5`) → default 30.

## Health Check

Healthcheck cada 10 s con timeout 5 s:

```bash
docker compose -f docker-compose.prod.yml exec meta-publisher sh -c \
  '[ -f /tmp/meta-publisher-health ] && [ $(( $(date +%s000) - $(cat /tmp/meta-publisher-health) )) -lt 5000 ]'
```

- **Healthy:** archivo actualizado hace < 5 s
- **Unhealthy:** archivo ausente o desactualizado → container se detiene y reinicia (policy)

Log directo de salud:

```bash
docker compose -f docker-compose.prod.yml inspect meta-publisher | grep -A 10 Health
```

## Diagnostics

### Ver stats de publicación

```bash
docker compose -f docker-compose.prod.yml logs meta-publisher --tail 10
```

Línea cada ~60 eventos. Busca:
- `boot_id` (16 hex): debe ser consistente hasta un restart
- `seq` (entero): debe incrementar en +1

### Detectar cambios de boot_id (restarts)

```bash
docker compose -f docker-compose.prod.yml logs meta-publisher | grep 'boot_id' | sort | uniq -c
```

Cada boot_id debe aparecer ~60 veces (log cada 60 eventos) antes de un cambio.

### Medir latencia de evento

Observer local (desde el host, requiere acceso a red teremoqwow-prod):

```bash
docker run --rm --network teremoqwow-prod \
  teremoqwow-meta-track:1 observe --window 10
```

Salida esperada (ejemplo):
```json
{
  "connected": true,
  "objects": 9,
  "bytes": 1053,
  "first_seq": 42,
  "last_seq": 50,
  "boot_ids": ["a1b2c3d4e5f6a1b2"],
  "monotonic": true,
  "window_seconds": 10
}
```

Criterios PASS (para Pipeline ingest.data):
- `connected: true`
- `objects >= 10` (en ventana 20 s de producción; escala con ventana de test)
- `monotonic: true` (seq estrictamente creciente por boot_id)

## Troubleshooting

### Container no arranca o se reinicia continuamente

Revisión:

1. **Logs de error:**
   ```bash
   docker compose -f docker-compose.prod.yml logs meta-publisher --tail 50
   ```

2. **Relay disponible:**
   ```bash
   docker compose -f docker-compose.prod.yml exec moq-relay sh -c 'echo > /dev/tcp/localhost/8090' && echo OK
   ```

3. **Red correcta:**
   ```bash
   docker compose -f docker-compose.prod.yml exec meta-publisher sh -c 'ping -c 1 moq-relay'
   ```

4. **Imagen construida:**
   ```bash
   docker images | grep teremoqwow-meta-track
   ```

### No hay eventos recibidos en Observer

1. **¿Publisher activo?**
   ```bash
   docker compose -f docker-compose.prod.yml ps meta-publisher
   ```
   Status debe ser `Up (healthy)` o `Up`.

2. **¿Relay recibe broadcasts?**
   ```bash
   docker compose -f docker-compose.prod.yml logs moq-relay | grep -i announce | tail -5
   ```
   Debe haber línea con `anon/live1-meta` recientemente.

3. **¿Conexión del observer?**
   Ejecuta observer con ventana pequeña:
   ```bash
   docker run --rm --network teremoqwow-prod --name obs-test \
     teremoqwow-meta-track:1 observe --window 2
   ```
   Si sale `connected: false` → problema de conectividad (DNS, firewall, TLS).

### Latencia alta o pérdida de eventos

**Síntoma:** `objects < 10` en ventana 20 s (Pipeline muestra FAIL).

1. **Carga del relay:**
   ```bash
   docker compose -f docker-compose.prod.yml logs moq-relay | tail -50 | grep -i error
   ```

2. **CPU/memoria del publisher:**
   ```bash
   docker stats meta-publisher
   ```
   Si CPU o MEM muy altos, hay contención. Aumentar limits en compose si es necesario.

3. **Jitter de intervalo:**
   Publisher usa timer con corrección de deriva. Logs cada 60 eventos. Si ves logs irregulares en tiempo (>70 s entre líneas), hay problema de planificación del SO.

### boot_id no cambia en restart

Si ves el mismo `boot_id` después de un reinicio → el container se está re-usando sin reinicio real.

Verificar:

```bash
docker inspect meta-publisher | grep -E 'Id|RestartCount|State'
```

Si `RestartCount` = 0, no ha reiniciado de verdad (es el mismo container).

Force restart:

```bash
docker compose -f docker-compose.prod.yml restart meta-publisher
```

## Recovery (after relay crash)

1. **Relay se reinicia:** publisher detecta desconexión, backoff 1→5 s, reconecta solo.
2. **Publisher se reinicia:** `restart: unless-stopped` lo levanta automáticamente.
   Si el relay lleva caído más de ~2,5 min (30 intentos agotados), el publisher
   hace `exit(1)` con log `FATAL` y Docker lo reinicia; el ciclo se repite hasta
   que el relay vuelve.
3. **Tiempo esperado:** < 15 s desde evento de fallo hasta primer evento publicado post-recovery.

Verificar post-recovery:

```bash
docker compose -f docker-compose.prod.yml logs meta-publisher | tail -5
```

Debe haber línea con `Connected! Starting to publish...` reciente.

## Configuration

Env vars en `docker-compose.prod.yml`:

| Var | Default | Rango | Descripción |
|-----|---------|-------|------------|
| `MOQ_URL` | `http://moq-relay:8090/` | URL | Endpoint del relay (interno) |
| `BROADCAST` | `anon/live1-meta` | `anon/live1-meta` | **Guardado: no cambiar** |
| `TRACK` | `heartbeat` | | Nombre del track |
| `INTERVAL_MS` | `1000` | 100-10000 | Cadencia en ms (1 Hz = 1000 ms) |
| `HEALTH_MARKER_PATH` | `/tmp/meta-publisher-health` | | Archivo de health (lectura por healthcheck) |

Para ajustar en producción:

```yaml
# docker-compose.prod.yml
environment:
  INTERVAL_MS: 2000  # 0.5 Hz (más lento, menos recursos)
```

Luego:

```bash
docker compose -f docker-compose.prod.yml up -d meta-publisher
```

## Schema

Evento publicado (un por frame, ~1 Hz):

```json
{
  "v": 1,
  "boot_id": "0123456789abcdef",
  "seq": 42,
  "emitted_at": "2026-10-12T16:47:00.123Z",
  "source_id": "anon/live1"
}
```

Validación: `schemas/media/v1/meta-heartbeat.json`

## Pipeline Integration

Pipeline Collector ejecuta observer cada 20 s:

```bash
# Colector bash (scripts/pipeline-collector.sh)
docker run --rm --network teremoqwow-prod teremoqwow-meta-track:1 \
  observe --window 20
# Salida → scripts/pipeline_meta_observe.py (convierte a TS format)
# → scripts/pipeline_obs.py (clasifica como PASS/FAIL/UNKNOWN)
# → Redis → Admin Dashboard
```

Criterio de `ingest.data`:
- **PASS:** connected ✓ + objects ≥ 10 ✓ + monotonic ✓
- **FAIL:** connected pero insuficientes objetos o no monótono
- **UNKNOWN:** no conectó o colector error

TTL de observación: 1200 s (20 min), se renueva cada 20 s.

## Alerts (Prometheus)

Configurar en `config/prometheus/rules/`:

```yaml
- alert: MetaPublisherDown
  expr: up{job="meta-publisher"} == 0
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Meta-publisher is down"

- alert: MetaPublisherPipelineUnknown
  expr: pipeline_ingest_data_result == "UNKNOWN"
  for: 15m
  labels:
    severity: warning
```

Ver Grafana: `Meta-Publisher Health` dashboard (si existe).

---

**Last Updated:** 2026-10-12
**Maintenance:** DevOps Team
**Escalation:** See [SECURITY.md](../../SECURITY.md) for incident response.
