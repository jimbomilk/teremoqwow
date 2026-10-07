# Runbook: Ingest SRT desde Larix Broadcaster

**Audiencia:** Operadores, productores, ingenieros de streaming.  
**Objetivo:** Configurar y verificar que Larix Broadcaster en un móvil/tablet transmite vídeo/audio en vivo a producción vía SRT.

---

## 1. Configuración en Larix Broadcaster

### Conexión

1. **Aplicación:** Larix Broadcaster (iOS/Android, descargar de App Store/Play Store).
2. **Connection Type:** Seleccionar **URL personalizada**.
3. **URL:** `srt://wow.teremoq.com:8890`
4. **Mode:** **Caller** (Larix inicia la conexión hacia el servidor).
5. **Passphrase:** **Dejar vacío** (el ingest SRT no autentica por passphrase).
6. **Stream ID:** **Obligatorio, no vacío.** Poner, por ejemplo, `live1`. El listener rechaza conexiones sin Stream ID (`rejecting SRT: no usable stream id`). El valor concreto no se usa para enrutar: se publica siempre en `anon/live1`.

### Configuración de Vídeo

| Parámetro | Valor | Razón |
|-----------|-------|-------|
| **Codec** | H.264 (AVC) | Compatibilidad universal; HEVC (H.265) **NO** soportado |
| **Resolución** | 1280x720 | Equilibrio calidad/ancho de banda |
| **Frame rate** | 30 fps | Broadcast estándar |
| **Keyframe interval** | 1 segundo (cada 30 frames) | Sincronización de relay y SLA de latencia (<700 ms) |
| **Profile** | Main | Decodificación amplia |
| **B-frames** | 0 (desactivar) | Mejora latencia; el relay no necesita buffer bidi |
| **Bitrate** | ~2500 kbps | ~315 KB/s; ajustar por ancho de banda disponible del móvil |

### Configuración de Audio

| Parámetro | Valor |
|-----------|-------|
| **Codec** | AAC (LC) |
| **Sample rate** | 48 kHz |
| **Channels** | Estéreo (2) |
| **Bitrate** | 128 kbps |
| **Normalization** | EBU R128: -23 LUFS |

### Verificar Antes de Emitir

- ✅ Conexión WiFi o LTE estable (>3 Mbps de upload recomendado).
- ✅ Batería del dispositivo >50%.
- ✅ Micrófono y cámara con permisos en el SO.
- ✅ No hay otras apps consumiendo ancho de banda.

---

## 2. Verificación en el Servidor Producción

### Desde el servidor (SSH o consola Docker)

Después de que Larix comience a emitir, verificar en **tiempo real** los logs del contenedor ingest:

```bash
# SSH a wow.teremoq.com (como deploy@...)
ssh deploy@wow.teremoq.com

# Entrar en el proyecto
cd /opt/teremoqwow

# Ver logs del ingest SRT (últimas 50 líneas, en vivo)
docker logs -f --tail 50 <nombre-del-proyecto>-srt-ingest-1
```

**Indicadores de éxito:**
- Aparece `Received SRT connection from <IP>` o similar.
- No hay errores de bind/conexión (puerto 8890 ocupado, etc.).
- Los logs continúan sin errores de I/O.

### Desde fuera (si hay firewall permisivo)

Si el firewall de Vultr permite conexiones remotas al relay desde otra máquina:

```bash
# En otra máquina (ej. tu laptop), con Docker instalado
docker run --rm moqdev/moq:0.12.7 \
  --connect tcp://wow.teremoq.com:4444/anon \
  --broadcast anon/live1 \
  fetch catalog.json
```

**Respuesta esperada:**
```json
{
  "tracks": [
    {
      "namespace": "anon/live1",
      "name": "video",
      "kind": "video",
      "codec_config": { "codec": "avc1.42E01E", ... }
    },
    {
      "namespace": "anon/live1", 
      "name": "audio",
      "kind": "audio",
      "codec_config": { "codec": "mp4a.40.2", ... }
    }
  ]
}
```

Si el JSON contiene ambas pistas (vídeo + audio), el ingest está funcionando. ✓

---

## 3. Ver el Stream en el Player

### Embed en página web

Compartir este URL con el operador/espectador:

```
https://wow.teremoq.com/player/?embed=1&broadcast=anon%2Flive1&relay=https%3A%2F%2Fwow.teremoq.com%3A4443%2Fanon
```

**Decodificación de parámetros:**
- `embed=1`: player sin UI de navegación, solo el vídeo.
- `broadcast=anon%2Flive1`: la transmisión actual (`anon/live1` URL-encoded).
- `relay=https%3A%2F%2Fwow.teremoq.com%3A4443%2Fanon`: WebTransport TLS al relay de producción.

### Verificar lip-sync (A/V)

Abrir las **Developer Tools** del navegador (F12):
- Tab **Console**: buscar líneas con `lip-sync` o `A/V offset`.
- Tab **Performance**: grabar 10 s de reproducción y buscar fotogramas perdidos o rebuffers.

**SLA:** Lip-sync < 45 ms. Si es mayor, revisar:
1. Bitrate: ¿Larix envía constantemente?
2. Red: ¿Hay pérdida de paquetes UDP?
3. Servidor: ¿CPU/memoria del relay está saturada?

---

## 4. Solución de Problemas

### Larix muestra "Connection Failed" aunque el puerto está abierto

**Causa probable:** Stream ID vacío. El listener rechaza la conexión SRT sin Stream ID.

**Verificación:** en los logs del contenedor `srt-ingest` aparece
`rejecting SRT: no usable stream id ... stream_id=None`.

**Acción:** en Larix, poner cualquier Stream ID no vacío (por ejemplo `live1`).

### Larix muestra "Connection Failed"

**Causa probable:** El firewall de Vultr bloquea el puerto 8890/UDP.

**Verificación:**
```bash
# En el servidor producción
sudo ufw status | grep 8890
```

**Esperado:**
```
8890/udp                   ALLOW      Anywhere
```

**Acción:** Si falta, abrir el puerto:
```bash
sudo ufw allow 8890/udp
```

### Larix conecta pero no hay vídeo en el player

**Causa probable:** El relay no recibe datos del ingest SRT.

**Verificación:**
```bash
# Ver los logs con más contexto
docker logs <proyecto>-srt-ingest-1 | grep -i "error\|warning"

# Si el relay está en pausa:
docker logs <proyecto>-moq-relay-1 | grep -i "anon/live1"
```

**Acciones:**
1. Reiniciar Larix (dejar de emitir 5 s, volver a iniciar).
2. Reiniciar el contenedor ingest:
   ```bash
   docker compose -f docker-compose.prod.yml restart srt-ingest
   ```
3. Verificar que la URL en Larix sea exactamente `srt://wow.teremoq.com:8890` (sin paths).

### Latencia muy alta (>1 s)

**Causa probable:** Configuración de latencia en Larix o buffer del relay.

**Verificación:**
```bash
# Ver el flag --latency en docker-compose.prod.yml
grep -A 2 "latency" docker-compose.prod.yml
```

**Esperado:**
```yaml
- --latency
- 500ms
```

**Acción:** Si es > 500 ms, reducir a 300 ms y reiniciar:
```bash
# Editar docker-compose.prod.yml, cambiar --latency a 300ms
docker compose -f docker-compose.prod.yml up -d srt-ingest
```

### Audio distorsionado o desfasado

**Verificación del codec:**
```bash
# En el servidor, verificar que el stream se capturó con AAC
docker exec <proyecto>-moq-relay-1 bash -c \
  "moq --connect tcp://localhost:4444/anon --broadcast anon/live1 export ts | \
   ffprobe -v error -show_streams -of json - 2>/dev/null | \
   jq '.streams[] | select(.codec_type==\"audio\")'"
```

**Esperado:**
```json
{
  "codec_type": "audio",
  "codec_name": "aac",
  "sample_rate": "48000",
  "channels": 2
}
```

**Acción:** Si no es AAC, revisar en Larix que esté configurado como descrito en **sección 1**.

---

## 5. Advertencias de Seguridad y Limites

⚠️ **IMPORTANTE: Conocer los límites arquitectónicos antes de producción.**

### Sin Autenticación en SRT

El puerto 8890/UDP **acepta cualquier conexión SRT** desde la red pública si Vultr/firewall lo permite. **Cualquiera que conozca `wow.teremoq.com:8890` puede publicar en `anon/live1`.**

**Mitigación:**
- Firewall de Vultr: restringir 8890/UDP solo a IPs conocidas (si es streaming punto a punto).
- Relay con autenticación: futuro (requiere cambios en moqdev/moq CLI).

### Un Único Broadcast Fijo

El ingest está configurado para **siempre publicar en `anon/live1`**, independientemente de qué envíe Larix. No hay soporte para múltiples streams.

**Para múltiples broadcasts:** Desplegar varios contenedores `srt-ingest` con diferentes puertos y `--broadcast <path>` únicos.

### Firewall de Vultr

Aunque Docker publique 8890/UDP en el host, el **firewall de nivel infraestructura de Vultr** puede bloquearlo. **Verificar:**

⚠️ **NOTA:** `nc -u -z` es un falso positivo con UDP (dice «succeeded» incluso sin listener). En su lugar, usar un handshake SRT real:

```bash
# Desde otra máquina (ej. tu laptop), con ffmpeg instalado
ffmpeg -loglevel error \
  -f lavfi -i testsrc2=size=320x180:rate=10 -t 3 \
  -c:v libx264 -preset ultrafast -f mpegts \
  "srt://wow.teremoq.com:8890?mode=caller&streamid=live1&connect_timeout=5000" \
  -y /dev/null

# Si termina sin error (exit code 0): puerto está abierto y recibe SRT.
# Si da "Input/output error": puerto bloqueado o sin listener.
```

**Alternativa sin ffmpeg:**

```bash
# Verificar que la regla UFW existe en el servidor
ssh deploy@wow.teremoq.com "sudo ufw status | grep 8890"
```

Si está bloqueado en Vultr:
1. Acceder a panel de Vultr: Firewall → Rules.
2. Añadir regla: Inbound UDP 8890 desde tu red (o 0.0.0.0/0).
3. Guardar y esperar ~30 s.

---

## 6. Enlaces Relacionados

- **Media pipeline:** [`../../config/moq-mux/README.md`](../../config/moq-mux/README.md) — configuración de codecs de ingreso.
- **Relay:** [`../../relay/README.md`](../../relay/README.md) — arquitectura del relay MoQ.
- **Player:** [`../../player/README.md`](../../player/README.md) — verificación de reproducción.

---

## Historial

- **2026-10-07:** Runbook inicial para moqdev/moq:0.12.7 + Larix Broadcaster.
