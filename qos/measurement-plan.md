# Plan de Medición — Fase 0

**Objetivo**: Procedimiento reproducible para medir latencia glass-to-glass end-to-end usando `moq-clock-ietf` y `moq_timing_sink`, validar contra criterio P95 ≤ 700ms.

**Scope**: Medición en entorno **dev/staging** (LAN, hardware conocido). Fase 1+ incluirá telemetría en prod.

---

## 1. Setup de la pipeline end-to-end

### 1.1 Componentes y orden de arranque

La pipeline completa (según `docs/architecture.md`):

```
Encoder → SRT bond → MediaMTX → moq-mux → moq-relay → Player
                                   ↓
                           moq-clock-ietf (track `sync`)
```

**Dependencias**:
- Docker Compose para MediaMTX, moq-mux, moq-relay, player mock.
- `moq-clock-ietf` crate (Rust) ya integrado en moq-mux o relay.
- `moq_timing_sink` (browser endpoint en player) para captura de latencia.

### 1.2 Comandos de arranque

**A. Start SRT bond** (issue #53):

```bash
cd config/srt-bond
docker-compose up -d
# Esperar 2s para que bind ports 8891, 8892, 8890
```

**B. Start MediaMTX** (issue #52):

```bash
cd config/mediamtx
docker-compose -f docker-compose.yml up -d
# Logs: MediaMTX listening on :1935 (RTMP), :8554 (RTSP), :8889 (SRT listener)
# Check: curl http://localhost:9997/stats
```

**C. Start moq-mux + FFmpeg transcodification** (issue #56):

```bash
cd config/moq-mux
# Asumir que moq-mux está dockerizado con FFmpeg
docker-compose up -d
# Esperar 3-5s para setup de canales
# Logs: moq-mux listening on :9080 (MoQ)
```

**D. Start moq-relay-ietf** (issue #54):

```bash
cd config/relay
docker-compose up -d
# Esperar 2s para bind
# Check: curl http://localhost:7777/health (si expone health endpoint)
```

**E. Start player test instance** (issue #57):

```bash
cd player
npm install  # si no está hecho
npm run dev  # Vite dev server en http://localhost:5173
```

Alternativamete, usar HTTP server mock:

```bash
cd player
python3 -m http.server 5173 &
# Abierto en http://localhost:5173
```

### 1.3 Inyección de vídeo de prueba

Usar un archivo de vídeo de prueba corto (~5 minutos) con **overlays de timestamp** para validación manual:

```bash
# Generar 5min de test pattern con FFmpeg
ffmpeg -f lavfi -i testsrc=size=1280x720:duration=300 \
  -f lavfi -i sine=f=440:d=300 \
  -c:v libx265 -preset veryfast \
  -c:a aac \
  -t 300 \
  -y /tmp/test-5min.mp4

# Enviar a SRT bond en encoder A (mock):
ffmpeg -re -i /tmp/test-5min.mp4 \
  -c:v copy -c:a copy \
  -f mpegts srt://localhost:8891?mode=send
```

**Nota**: En producción, reemplazar con encoder real (hardware RTSP/SRT).

---

## 2. Captura de métricas

### 2.1 Player emite evento `moq:latency`

**Asunción**: Player (después de issue #57) expone latencia vía:

1. **WebSocket endpoint** `/metrics/latency` que emite eventos JSON:
   ```json
   {
     "timestamp_ms": 1704067200000,
     "pts_ms": 1704067100234,
     "render_ts_ms": 1704067200123,
     "latency_ms": 889,
     "ntp_offset_ms": -12
   }
   ```

2. **O alternativa**: Escribir JSON Lines a fichero local:
   ```
   /tmp/player-latency.jsonl
   ```

3. **O Prometheus metrics** endpoint:
   ```
   GET /metrics
   # moq_player_latency_ms{quantile="p50"} 400
   # moq_player_latency_ms{quantile="p95"} 650
   ```

**Para Fase 0**, asumimos **WebSocket endpoint** (#1) o **fichero JSONL** (#2).

### 2.2 Captura desde cliente (script bash)

Script `measure-e2e.sh` (ver sección 4) conecta a `/metrics/latency` (WebSocket) y recoge eventos durante N segundos:

```bash
# Pseudocódigo en measure-e2e.sh:
while [ $ELAPSED -lt $DURATION ]; do
  # Conect WebSocket, read latency events, append to CSV
  # O: tail -f /tmp/player-latency.jsonl | jq '.latency_ms' >> /tmp/latency.csv
done
```

### 2.3 Captura desde moq-clock-ietf (track `sync`)

**Alternativa**: moq-clock-ietf (Rust, issue #56) emite un track `sync` con pulsos NTP-alineados. El player puede leer este track y correlacionar con su PTS local para **verificar lip-sync** (offset < 45ms es acceptable).

Verificación en player:

```javascript
// player/src/moq-watch.ts (pseudo-código)
const syncTrack = await session.subscribe('sync');
const syncReader = syncTrack.read();

for await (const object of syncReader) {
  const syncPts = object.timestamp_wallclock_ns;
  const playerLocalTime = performance.now() * 1e6;  // ns
  const offset = Math.abs(syncPts - playerLocalTime) / 1e6;  // ms
  
  if (offset > 45) {
    console.warn(`Lip-sync alert: offset ${offset}ms > 45ms`);
  }
}
```

---

## 3. Procedimiento paso a paso (manual)

### 3.1 Prep (10 min)

1. Terminal A: `cd /home/jimbomilk/projects/teremoqwow`
2. Terminal B (SRT bond): `cd config/srt-bond && docker-compose up`
3. Terminal C (MediaMTX): `cd config/mediamtx && docker-compose up`
4. Terminal D (moq-mux): `cd config/moq-mux && docker-compose up`
5. Terminal E (relay): `cd config/relay && docker-compose up`
6. Terminal F (player dev): `cd player && npm run dev` (esperar "ready in XXms")

### 3.2 Inyectar vídeo (encoder mock)

Terminal G:

```bash
# Generar test pattern si no existe
[ ! -f /tmp/test-5min.mp4 ] && \
  ffmpeg -f lavfi -i testsrc=size=1280x720:duration=300 \
    -f lavfi -i sine=f=440:d=300 \
    -c:v libx265 -preset veryfast -c:a aac \
    -y /tmp/test-5min.mp4

# Enviar a SRT bond (encoder A)
ffmpeg -re -i /tmp/test-5min.mp4 \
  -c:v copy -c:a copy \
  -f mpegts \
  srt://localhost:8891?mode=send \
  2>&1 | tee /tmp/encoder-log.txt
```

**Esperar ~5 segundos** para que la pipeline se estabilice (llenar buffers, establecer conexiones QUIC).

### 3.3 Abrir player e iniciar medición

Terminal H:

```bash
# Navegar a player en navegador Chrome/Firefox (dev tools abierto)
# O usar curl + WebSocket cliente simple

# Opción 1: websocat (CLI tool para WebSocket)
websocat ws://localhost:5173/metrics/latency | tee /tmp/latency-raw.jsonl

# Opción 2: usar script bash (ver sección 4, `measure-e2e.sh`)
bash qos/scripts/measure-e2e.sh --duration 300
```

**Duración**: ~5 minutos (tiempo del vídeo de prueba).

### 3.4 Análisis

Después de 5 min, script produce `/tmp/latency-results.csv`:

```csv
timestamp_ms,latency_ms
1704067200000,420
1704067200033,410
1704067200066,435
...
```

Calcular percentiles:

```bash
bash qos/scripts/measure-e2e.sh --analyze /tmp/latency-results.csv
# Output:
# p50: 410ms
# p95: 650ms
# p99: 890ms
# Status: PASS (p95 ≤ 700ms)
```

---

## 4. Script de automatización: `measure-e2e.sh`

Ver sección 5 abajo. El script:

1. **Setup**: Valida dependencias, arranca pipeline docker.
2. **Captura**: Inyecta vídeo de prueba, conecta a player, recoge latencias.
3. **Análisis**: Calcula p50/p95/p99 con `sort` + `awk`.
4. **Validación**: Exit code 0 si P95 ≤ 700ms; exit 1 en otro caso.

---

## 5. Validación contra criterio

### 5.1 Criterios de aceptación Fase 0

| Métrica | Criterio | Evaluado por |
|---|---|---|
| P50 latencia e2e | < 400ms | script `measure-e2e.sh` |
| P95 latencia e2e | ≤ 700ms | **script `measure-e2e.sh`** (exit code) |
| P99 latencia e2e | < 1000ms | log informativo |
| Muestras | ≥ 1000 frames en 5 min (≥200fps @ 300s) | validación en script |
| Lip-sync offset | < 45ms (si disponible moq-clock-ietf) | log, no blocking para Fase 0 |

### 5.2 Interpretación de resultados

**PASS**: P95 ≤ 700ms + ≥1000 muestras
```bash
$ bash qos/scripts/measure-e2e.sh
p50: 410ms
p95: 650ms
p99: 890ms
samples: 4500
status: PASS
(exit 0)
```

**FAIL**: P95 > 700ms → revisar riesgos en `latency-budget.md`
```bash
$ bash qos/scripts/measure-e2e.sh
p50: 510ms
p95: 850ms  ← EXCEEDS 700ms
p99: 1200ms
samples: 3800
status: FAIL - p95 exceeds budget
(exit 1)
```

**INCONCLUSIVE**: < 1000 muestras → volver a ejecutar
```bash
$ bash qos/scripts/measure-e2e.sh
p50: 380ms
p95: 620ms
p99: 750ms
samples: 450  ← INSUFFICIENT
status: INCONCLUSIVE - too few samples
(exit 2)
```

### 5.3 Debugging

Si P95 > 700ms:

1. **Verificar encoder**: `ffmpeg -v debug ...` → buscar frame drops, latencia anormal.
2. **Verificar MediaMTX**: `curl http://localhost:9997/stats | jq '.medias'` → buffers, conectados.
3. **Verificar relay**: `docker logs <relay-container> | grep latency` → retransmisiones, congestion.
4. **Verificar player**: Dev tools → WebCodecs decode time, event loop jitter.

---

## 6. Ejemplos de comandos útiles

### Inspeccionar relay stats

```bash
# Si relay expone endpoint /stats
curl -s http://localhost:7777/stats | jq '.connections[] | {rtt, loss, latency}'

# O via logs
docker logs teremoqwow_relay | grep -i 'rtt\|latency' | tail -20
```

### Inspeccionar MediaMTX ingesta

```bash
curl -s http://localhost:9997/stats | jq '.'
# Buscar "receivedFrames", "droppedFrames" para cada media
```

### Extraer muestras de latencia bruto (jq)

```bash
# Si se captura en JSONL
jq -r '.latency_ms' /tmp/latency-raw.jsonl > /tmp/latency.csv
sort -n /tmp/latency.csv | awk '{a[NR]=$1} END {
  n=NR;
  print "p50: " a[int(n*0.5)] "ms";
  print "p95: " a[int(n*0.95)] "ms";
  print "p99: " a[int(n*0.99)] "ms"
}'
```

### Generar test pattern con timestamps visibles

```bash
# Drawtext filter in FFmpeg para overlay timestamps
ffmpeg -f lavfi \
  -i testsrc=size=1280x720:duration=300 \
  -vf "drawtext=fontfile=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf: \
        text='%{frame_num}': fontsize=48: fontcolor=white: x=10: y=10" \
  -c:v libx265 -preset veryfast \
  -y /tmp/test-5min-annotated.mp4
```

---

## 7. Dependencias esperadas

### Sistema

- `bash` 4.0+
- `jq` 1.6+ (JSON parsing)
- `awk` (cálculo de percentiles)
- `curl` (health checks)
- `docker`, `docker-compose` (orquestación)
- FFmpeg 4.0+ (generación de test pattern)

### En repositorio

- `config/srt-bond/docker-compose.yml` (#53)
- `config/mediamtx/docker-compose.yml` (#52)
- `config/moq-mux/docker-compose.yml` (#56)
- `config/relay/docker-compose.yml` (#54)
- `player/` (HTTP server + WebSocket `/metrics/latency`) (#57)

### Externos (opcional, future)

- `websocat`: CLI WebSocket client → `cargo install websocat`
- ClickHouse: para persistencia de métricas → Fase 1

---

## 8. Próximos pasos (Fase 1+)

1. **Prometheus scraping**: Relay + player exponen `/metrics` en formato Prometheus.
2. **ClickHouse sink**: Telemetría persiste en ClickHouse para análisis histórico.
3. **Grafana dashboards**: p50, p95, p99 latency over time; jitter heatmaps.
4. **Alertas**: Prometheus alert rules → `p95 > 800ms for > 5min`.
5. **Geo-latency**: Diferentes relays (edge CDN) → medición por región.

---

## Apéndice: Fórmula de latencia glass-to-glass

```
latency_ms = (render_ts - pts_timestamp) - ntp_offset

Donde:
  - render_ts = performance.now() en el navegador (ms)
  - pts_timestamp = PTS del frame del servidor (ms, convertido de ns)
  - ntp_offset = diferencia reloj cliente - servidor (ms, estimado al inicio)

Ejemplo:
  - Servidor genera frame en t=0 con PTS=1704067100000 (NTP wallclock)
  - Cliente recibe + decodifica en t=50ms
  - Client render en t=150ms (performance.now())
  - ntp_offset = -10ms (cliente 10ms adelantado)
  
  latency = (150 - 100000) - (-10) = ... espera, esto no tiene sentido en ms.
  
  Aclaración (ver player/src/latency.ts):
    - pts_timestamp se expresa en ms (divide ns / 1e6)
    - render_ts y ntp_offset están en ms
    
  Ejemplo corregido:
    - PTS = 1704067100000 ms (wallclock server absoluto)
    - render_ts = 5000 ms (performance.now() relativo a navigation start)
    - ntp_offset = 1704067095000 ms (diferencia absoluta)
    
    latency = (5000) - (1704067100000 - 1704067095000) = 5000 - 5000 = 0 (no, simplificando)
    
  Ver implementación en player/src/latency.ts para detalles exactos.
```
