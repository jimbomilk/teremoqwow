# Runbook: Source FFmpeg — Fuente de vídeo+audio permanente

**Audiencia:** Operadores, ingenieros de infra, productores.  
**Objetivo:** Verificar que el servicio `source-ffmpeg` publica vídeo+audio deterministas por SRT a `srt-ingest`, para cubrir el prerrequisito de Fase 0 (ingesta mínima viable sin Larix).

---

## 1. Descripción del servicio

### ¿Qué es?

`source-ffmpeg` es un contenedor FFmpeg siempre activo en producción (`wow.teremoq.com`).
Genera y publica:
- **Vídeo:** testsrc2 (patrón de test 1280x720 @ 30 fps, determinista).
- **Audio:** tono sine 1000 Hz @ 48 kHz estéreo (determinista).

### ¿Por qué?

Sustituye las pruebas manuales con Larix, permitiendo que la ingesta, relay y reproducción se verifiquen continuamente sin intervención humana.

### ¿Dónde publica?

Vía SRT interno a `srt-ingest:8890` (red `teremoqwow-prod`), streamid `live1`.  
El mismo listener que acepta Larix Broadcaster desde producción (UDP, sin autenticación).

---

## 2. Verificación en producción

### Ver logs en tiempo real

```bash
# SSH a wow.teremoq.com
ssh deploy@wow.teremoq.com
cd /opt/teremoqwow

# Ver logs del servicio source-ffmpeg (últimas 100 líneas, en vivo)
docker logs -f --tail 100 teremoqwow-source-ffmpeg-1
```

**Indicadores de éxito (gates de transporte):**
- No hay errores de conexión a `srt-ingest`.
- No hay crashes ni restarts frecuentes.
- FFmpeg sigue escribiendo frames (output log contiene `frame=NNNN`).

### Ver estado del contenedor

```bash
# Listar todos los servicios
docker compose -f docker-compose.prod.yml ps

# Buscar source-ffmpeg
docker ps | grep source-ffmpeg
```

**Esperado:**
```
teremoqwow-source-ffmpeg-1   ...   Up (minutes)
```

### Sonda: consultar estado JSON

```bash
# Ejecuta la sonda
bash scripts/probe-source-ffmpeg.sh
```

**Salida esperada:**
```json
{
  "source": "source-ffmpeg",
  "state": "running",
  "target": "srt-ingest:8890",
  "streamid": "live1",
  "broadcast": "anon/live1",
  "tracks": ["video", "audio"],
  "restart_count": 0,
  "checked_at": "2026-10-12T01:03:21Z"
}
```

Si `state` no es `running`, revisar logs.

### Verificar que srt-ingest recibe datos

```bash
# Ver logs de srt-ingest
docker logs -f --tail 20 teremoqwow-srt-ingest-1
```

**Indicadores:**
- Aparece `Received SRT connection from` (o similar, según versión moq).
- No hay errores de I/O.
- Los logs continúan sin interrupciones.

---

## 3. Configuración FFmpeg

### Comando FFmpeg

El servicio corre (simplificado, sin drawtext):

```bash
ffmpeg \
  -re -f lavfi -i "testsrc2=s=1280x720:r=30" \
  -re -f lavfi -i "sine=f=1000:r=48000" \
  -map "0" -map "1" \
  -c:v libx264 -profile:v baseline -bf 0 -g 30 -keyint_min 30 -sc_threshold 0 \
    -preset veryfast -tune zerolatency -pix_fmt yuv420p -r 30 \
  -c:a aac -ar 48000 -ac 2 -b:a 128k \
  -f mpegts "srt://srt-ingest:8890?mode=caller&streamid=live1&latency=500"
```

### Parámetros clave

| Parámetro | Valor | Razón |
|-----------|-------|-------|
| **Pacing** | -re (antes de cada lavfi) | Evita correr a 51x speed (~1 MB/s). Incidente FIX: #XXX |
| **Vídeo fuente** | testsrc2 (sin d=) | Determinista; patrón de test visible en player. Duración infinita (default). |
| **Resolución** | 1280x720 @ 30 fps | Broadcast estándar |
| **Keyframe interval** | -g 30 (1s @ 30fps) | SLA latencia P95 <700ms (issue #133) |
| **Codec vídeo** | H.264 baseline | Baja latencia (sin B-frames) |
| **Pix format** | yuv420p | Compatible con SRT/MPEG-TS |
| **Audio fuente** | sine 1000 Hz @ 48 kHz (sin d=) | Determinista; tono audible. Duración infinita (default). |
| **Codec audio** | AAC @ 128k | Estándar MPEG-TS |
| **Container** | MPEG-TS | Requerido por SRT listener |
| **SRT target** | srt://srt-ingest:8890 | Red interna; streamid=live1; latency=500ms |

**Nota histórica (INCIDENTE FIX):** En jrottenberg/ffmpeg:7.1-alpine, `testsrc2=d=0` genera duración cero → ffmpeg emitía 0 frames de vídeo (solo audio) a 51x speed (~1 MB/s), sin pacing. Solución: remover `d=0` de ambas entradas (lavfi no especifica duración → infinita) y añadir `-re` antes de cada lavfi para pacing en tiempo real.

---

## 4. Verificación de calidad audiovisual (manual)

**Gates automáticas:** Transporte y servicio (proceso ejecutándose, SRT conectado, bytes fluyendo, restart funcionando).

**Verificación de calidad (imagen, sonido):** Abre el player en wow.teremoq.com y revisa manualmente:
- ¿Se ve el vídeo (patrón de test testsrc2)?
- ¿Se escucha el audio (tono 1000 Hz)?
- ¿Hay lip-sync correcto (A/V < 45 ms)?

**Nota:** No hay validación automática de fps, GOP, timecode, B-frames, tono, silencio, etc. Esa es competencia de verificación humana.

---

## 5. Troubleshooting

### `source-ffmpeg` en estado `exited` o `restarting` frecuente

**Causa posible:** srt-ingest no está listo.

```bash
# Verificar que srt-ingest está running
docker ps | grep srt-ingest

# Si no está, iniciar:
docker compose -f docker-compose.prod.yml up -d srt-ingest

# Esperar unos segundos, luego reiniciar source-ffmpeg:
docker compose -f docker-compose.prod.yml up -d source-ffmpeg

# Ver logs
docker logs -f teremoqwow-source-ffmpeg-1
```

### `ffmpeg: Connection refused` o `Connection timed out`

**Causa posible:** srt-ingest no escucha en el puerto 8890, o la red `teremoqwow-prod` no está disponible.

```bash
# Verificar red
docker network inspect teremoqwow-prod

# Verificar puerto en srt-ingest
docker exec teremoqwow-srt-ingest-1 netstat -tunl | grep 8890
```

### `ffmpeg: memory usage high` o `CPU high`

**Causa posible:** Encoder está sin output (buffer lleno).

```bash
# Recolectar logs más detallados
docker logs --tail 500 teremoqwow-source-ffmpeg-1 | tail -50
```

Si los logs muestran `x264` sin avanzar o se repite `frame=...`, es posible que:
- El SRT listener está en condición de backpressure.
- El ancho de banda es insuficiente para 2500 kbps.

**Acción:** Reducir bitrate o GOP en docker-compose.prod.yml (editando el `command` de `source-ffmpeg`) y reiniciar.

### Deploy fallido: cambios en docker-compose.prod.yml no aplican

```bash
# Verificar sintaxis YAML
docker compose -f docker-compose.prod.yml config -q

# Si no hay errores, forzar pull e inicio
docker compose -f docker-compose.prod.yml pull source-ffmpeg
docker compose -f docker-compose.prod.yml up -d source-ffmpeg
```

---

## 6. Métrica de éxito (Gate de Fase 0)

✅ `docker ps` muestra `source-ffmpeg` en estado `Up`.  
✅ `probe-source-ffmpeg.sh` retorna `state=running`.  
✅ Catálogo MoQ (`admin-api /api/v1/catalog`) lista `anon/live1` con 2 tracks (video + audio).  
✅ Player en wow.teremoq.com reproduce el vídeo/audio **sin errores** (verificación humana).  

Si cualquiera de las primeras 3 falla: revisar logs y aplicar troubleshooting anterior.  
Si falla la 4ª: abrir el player, ver/escuchar el contenido, reportar si hay desincronización A/V o artefactos.

---

## 7. Próximos pasos

- **Fase 1:** Añadir ingest de data (telemetría, estadísticas) en broadcast hermano `anon/live1-meta`.
- **Fase 2:** Verificar relay y clustering MoQ.
- **Fase 3:** Verificar player y lip-sync.
- **Admin:** Página de status que consulta la sonda y muestra semáforos por fase.
