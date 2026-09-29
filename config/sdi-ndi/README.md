# SDI / NDI → MoQ Broadcast Gateway — issue #89

Procedimiento para conectar fuentes de señal profesional SDI (DeckLink) y NDI al relay MoQ
de teremoqwow. Los scripts de esta carpeta son comandos de referencia; ajusta los parámetros
de dispositivo según tu hardware antes de ejecutarlos.

## Requisitos

| Dependencia | Versión mínima | Notas |
|-------------|---------------|-------|
| FFmpeg | 6.x | Compilado con `--enable-decklink` (SDI) o `--enable-libndi_newtek` (NDI) |
| Blackmagic Desktop Video | 12.x | Solo SDI DeckLink; instalar antes de FFmpeg |
| NDI SDK | 5.x | Solo NDI; `libndi_newtek` debe estar en `LD_LIBRARY_PATH` |
| moq CLI | 0.12.7 | `moqdev/moq:0.12.7` Docker image |
| moq-relay | 0.15.7 | En marcha y accesible vía TCP |

## SDI via DeckLink

### 1. Identificar el dispositivo

```bash
ffmpeg -f decklink -list_devices 1 -i dummy 2>&1 | grep '\['
# Ejemplo de salida:
#   [decklink @ ...] DeckLink Duo 2 (1) - modo: 0 (NTSC)
#   [decklink @ ...] DeckLink Duo 2 (2)
```

### 2. Listar modos de vídeo del dispositivo

```bash
ffmpeg -f decklink -list_formats 1 -i "DeckLink Duo 2" 2>&1 | head -30
```

### 3. Capturar y publicar

Editar `ffmpeg-sdi-command.sh` con el nombre exacto del dispositivo y ejecutar:

```bash
DEVICE="DeckLink Duo 2" RELAY_TCP="tcp://moq-relay:4444" BROADCAST="live/sdi-1" \
  bash config/sdi-ndi/ffmpeg-sdi-command.sh
```

La señal SDI llega sin delay de transcodificación si el relay acepta H.264 passthrough.
El script fuerza `-tune zerolatency` para minimizar buffering.

## NDI

### 1. Listar fuentes NDI disponibles en la red

```bash
ffmpeg -f libndi_newtek -find_sources 1 -i dummy 2>&1 | grep 'Found'
# Ejemplo:
#   Found 2 NDI sources
#   [NDI] CAMARA-ESTUDIO-1 (192.168.1.10)
```

### 2. Capturar y publicar

```bash
NDI_SOURCE="CAMARA-ESTUDIO-1" RELAY_TCP="tcp://moq-relay:4444" BROADCAST="live/ndi-1" \
  bash config/sdi-ndi/ffmpeg-ndi-command.sh
```

## Topología

```
[DeckLink / NDI src]
        │
        ▼
   ffmpeg (captura + encode H.264/AAC)
        │  stdout (MPEG-TS pipe)
        ▼
   moq CLI --broadcast <namespace> import ts
        │  MoQ/TCP
        ▼
   moq-relay:4444
        │  clustering TCP qmux
        ▼
   relay federado (relay-2, relay-3…)
```

## Parámetros de latencia

- SDI: latencia extremo-a-extremo esperada < 500 ms con `-preset ultrafast -tune zerolatency`.
- NDI: latencia adicional ~100–200 ms por el protocolo NDI antes de FFmpeg.
- La segmentación GOP (`-g 60 -keyint_min 60`) alinea con los umbrales DTS del player ABR.

## Troubleshooting

| Síntoma | Causa probable | Acción |
|---------|---------------|--------|
| `Could not find codec parameters` | Modo SDI incorrecto | Listar formatos con `ffmpeg -list_formats 1` |
| `NDI: source not found` | Fuente fuera de la red mDNS | Usar `-i "NDI_SOURCE@IP"` directamente |
| Relay rechaza la conexión | Puerto 4444 no accesible | Verificar `--auth-public 'anon/**'` en relay |
| Vídeo con artefactos | Pérdida de frames en pipe | Aumentar `-thread_queue_size 512` en FFmpeg |
