# Runbook: Degradación de latencia E2E

**Severidad**: P2 (SLO P95 > 700 ms)  
**SLO afectado**: Latencia E2E P95 < 700 ms, lip-sync < 45 ms  
**RTO objetivo**: < 5 min

## Síntomas

- Alerta Grafana: `e2e_latency_p95 > 700` (regla en `config/prometheus/rules/`).
- `qos/scripts/measure-e2e.sh` reporta P95 fuera de SLO.
- Usuarios reportan desincronización audio/vídeo > 45 ms.

## Diagnóstico rápido

```bash
# 1. Medir latencia actual
bash qos/scripts/measure-e2e.sh

# 2. Verificar lip-sync
bash qos/scripts/verify-lipsync.sh

# 3. Verificar sincronización de tracks
bash qos/scripts/verify-sync-track.sh

# 4. Verificar sincronización PTS
bash qos/scripts/verify-pts-sync.sh
```

## Identificar el segmento degradado

| Segmento | Métrica Grafana | Umbral |
|---|---|---|
| Ingesta SRT → MediaMTX | `srt_input_latency_ms` | < 100 ms |
| Transcodificación | `ffmpeg_encode_latency_ms` | < 200 ms |
| MoQ relay → player | `moq_delivery_latency_ms` | < 400 ms |
| Lip-sync | `lipsync_delta_ms` | < 45 ms |

## Pasos de recuperación

1. **Latencia en ingesta SRT** (buffer de red):
   - Revisar `config/srt-bond/srt-bond.conf`: reducir `latency` si la red lo permite.
   - Verificar pérdida de paquetes: `ss -s` en el host del encoder.

2. **Latencia en transcodificación** (FFmpeg):
   - Verificar carga de CPU del host: `top` / `docker stats`.
   - Si CPU > 80 %: reducir resolución temporalmente (`-vf scale=960:540`) o migrar a instancia más potente.
   - Confirmar preset `ultrafast` y `tune zerolatency` en el comando FFmpeg activo.

3. **Latencia en relay MoQ** (buffer de grupo):
   - Revisar `config/relay/relay.toml`: campo `max-age` (objetivo ≤ 2 s).
   - Comprobar `moq_relay_group_age_ms` en Grafana.
   - Reiniciar relay si el buffer acumula grupos obsoletos.

4. **Lip-sync fuera de SLO**:
   - Verificar PTS del muxer en moq-mux: `bash qos/scripts/verify-pts-sync.sh`.
   - Si el delta es estable (sistemático): ajustar `audio_offset_ms` en la configuración del muxer.
   - Si el delta varía (jitter): revisar scheduling del contenedor (prioridad CPU/RT).

5. **Switching ABR causando latencia**:
   - Ejecutar `bash qos/scripts/test-switching.sh` para aislar.
   - Incrementar el umbral de switching en `player/src/abr.ts` si oscila en ancho de banda límite.

## Escalado

- > 5 min con P95 > 1 s → escalar a on-call.
- Degradación afecta a todos los clientes → activar modo de contingencia (reducir a un solo rendition).

## Post-mortem

Archivar en `qos/reports/` con formato `YYYY-MM-DD-incidente-latencia.md`.
