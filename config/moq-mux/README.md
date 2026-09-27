# config/moq-mux/

Configuración del pipeline de transcodificación ABR basado en **FFmpeg + moq-pub**
(binario `moq-pub` del crate [`moq-rs`](https://github.com/kixelated/moq-rs),
referido en la issue como *moq-mux*). Issue: [#56](https://github.com/jimbomilk/teremoqwow/issues/56).

---

## Objetivo

Leer la señal ya ingestada por MediaMTX, transcodificarla a tres calidades de
vídeo (High / Medium / Low) con GOP alineado cada 2 segundos y publicar los
tracks en el relay MoQ para que el player pueda hacer ABR.

---

## Diagrama

```
┌──────────────────────────────────────────────────────────────────────────┐
│  Broadcast                                                               │
│  SRT source  ──SRT──▶  MediaMTX :8890                                   │
│                        streamid=read:live-main                           │
└────────────────────────────┬─────────────────────────────────────────────┘
                             │  SRT (pull)
                             ▼
┌────────────────────────────────────────────────────────────────────────────┐
│  FFmpeg                                                                    │
│                                                                            │
│  -i srt://mediamtx:8890?streamid=read:live-main                           │
│                                                                            │
│  [0:v] split=3 ──▶ [v_high]  libx264  1920×1080  3000 kbps  Main@L4.0   │
│                ├──▶ [v_med]  libx264  1280×720   2000 kbps  Main@L3.1   │
│                └──▶ [v_low]  libx264   854×480   1000 kbps  Main@L3.0   │
│  [0:a]         ──▶           AAC-LC   48 kHz      128 kbps  stereo      │
│                                                                            │
│  Salida: MPEG-TS multiprograma → stdout (pipe)                            │
└────────────────────────────┬─────────────────────────────────────────────┘
                             │  pipe (stdin)
                             ▼
┌──────────────────────────────────────────────────────────────────────────┐
│  moq-pub                                                                 │
│  --url https://relay:4443                                                │
│  --namespace teremoqwow/dev/live1                                        │
│                                                                          │
│  Publica un track MoQ por PID MPEG-TS:                                  │
│    video-high  · video-medium  · video-low  · audio-main                │
│    (+ tracks *.init con el init segment de cada uno)                    │
└────────────────────────────┬─────────────────────────────────────────────┘
                             │  MoQ / QUIC
                             ▼
                    relay:4443  (moq-relay de moq-rs)
```

---

## Dependencias

| Componente | Versión mínima | Notas |
|---|---|---|
| FFmpeg | 6.0 | Con `libx264`, `libsrt`, `libopus` |
| moq-pub | git main | `cargo install --git https://github.com/kixelated/moq-rs moq-pub` |
| Rust toolchain | 1.75 | Para compilar moq-pub |

> moq-rs no publica imágenes Docker oficiales. Ver sección [Levantar con Docker](#levantar-con-docker).

---

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `MOQ_RELAY_URL` | `https://relay:4443` | URL QUIC del relay MoQ |
| `MOQ_NAMESPACE` | `teremoqwow/dev/live1` | Namespace MoQ del broadcast |
| `SRT_SOURCE` | `srt://mediamtx:8890?streamid=read:live-main` | URL SRT de MediaMTX |
| `FRAMERATE` | `30` | Framerate del source (determina `GOP_FRAMES = FRAMERATE × 2`) |
| `MOQ_JWT_TOKEN` | _(vacío)_ | Bearer JWT para autenticar con el relay. **Nunca hardcodear.** |
| `MOQ_INSECURE` | `true` | Omitir verificación TLS en dev (certs auto-firmados) |

---

## Levantar el pipeline

### Con cargo (desarrollo local)

```bash
# 1. Compilar moq-pub (sólo la primera vez)
cargo install --git https://github.com/kixelated/moq-rs --bin moq-pub

# 2. Arrancar el pipeline
cd /path/to/teremoqwow
bash config/moq-mux/run.sh
```

### Con cargo run desde el repo moq-rs

```bash
# Dentro del repo clonado de moq-rs:
ffmpeg ... -f mpegts pipe:1 \
| cargo run --bin moq-pub -- \
    --url https://relay:4443 \
    --namespace teremoqwow/dev/live1 \
    --insecure
```

### Levantar con Docker

No existe imagen oficial. Construir localmente:

```dockerfile
# Dockerfile.moq-pub  (en el repo moq-rs clonado)
FROM rust:1.75-slim AS builder
RUN apt-get update && apt-get install -y pkg-config libssl-dev
WORKDIR /build
COPY . .
RUN cargo build --release --bin moq-pub

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ffmpeg libssl3 && rm -rf /var/lib/apt/lists/*
COPY --from=builder /build/target/release/moq-pub /usr/local/bin/moq-pub
COPY config/moq-mux/run.sh /run.sh
ENTRYPOINT ["bash", "/run.sh"]
```

```bash
docker build -f Dockerfile.moq-pub -t teremoqwow/moq-pub:local .
docker run --rm \
  -e MOQ_RELAY_URL=https://relay:4443 \
  -e MOQ_NAMESPACE=teremoqwow/dev/live1 \
  -e SRT_SOURCE="srt://mediamtx:8890?streamid=read:live-main" \
  -e MOQ_INSECURE=true \
  --network teremoqwow_net \
  teremoqwow/moq-pub:local
```

---

## Verificar que el catálogo lista los 3 tracks

### 1. Consultar el endpoint del relay

```bash
# El relay expone el catálogo como un objeto MoQ CATALOG bajo el namespace.
# El endpoint HTTP equivalente depende de la implementación del relay;
# para moq-relay de moq-rs con WebTransport:
curl -k https://relay:4443/catalog/teremoqwow/dev/live1 | jq .
```

La respuesta esperada debe coincidir con [`example-catalog.json`](./example-catalog.json).

### 2. Validar el JSON contra el schema

```bash
# Instalar ajv-cli si no está disponible:
npm install -g ajv-cli ajv-formats

# Validar:
ajv validate \
  -s schemas/media/v1/catalog.json \
  -d config/moq-mux/example-catalog.json \
  --spec=draft2020 \
  --strict=false
```

Salida esperada: `config/moq-mux/example-catalog.json valid`.

### 3. Verificar alineación de keyframes (test de latencia)

Tras levantar el pipeline, comprobar que los keyframes están alineados entre
renditions y que la latencia extremo-a-extremo es ≤ objetivo:

```bash
# Inspeccionar keyframes de cada rendition desde el source SRT reencaminado
# (requiere acceso al MPEG-TS multiplexado, p.ej. via tee en run.sh):
ffprobe -v quiet -select_streams v:0 \
  -show_frames -of csv \
  -i srt://mediamtx:8890?streamid=read:live-main \
  | grep -w 1 | head -20
# key_frame=1 debe aparecer cada ~60 frames (2 s a 30 fps).

# Medir latencia SRT → relay con timestamp de primer keyframe visible:
# Comparar PTS del IDR en el stream de entrada con el PTS del objeto MoQ
# recibido por un subscriber de prueba.
```

> **Regla del pipeline**: cada cambio en `run.sh` debe ir acompañado de una
> verificación de keyframes y PTS antes de hacer commit.

---

## Decisiones de diseño

| Decisión | Elección | Razón |
|---|---|---|
| Transporte FFmpeg → moq-pub | **pipe** (stdout → stdin) | Sin puerto TCP extra; SIGPIPE propaga fallos; kernel gestiona buffering |
| Audio compartido vs replicado | **Un único track AAC** | CPU y ancho de banda mínimos; el player ABR siempre usa el mismo track de audio |
| Framerate de source variable | Conversión CFR con `-r` | Garantiza `-g` exacto y `force_key_frames` precisos aunque el source sea VFR |
| Config TOML vs script | **run.sh** | moq-pub no acepta config TOML (usa flags CLI); script parametrizable por env vars |

---

## Archivos en este directorio

| Fichero | Descripción |
|---|---|
| `run.sh` | Pipeline completo FFmpeg → moq-pub, parametrizado por env vars |
| `example-catalog.json` | Catálogo MoQ de referencia con los 4 tracks esperados (3 vídeo + 1 audio) |
| `README.md` | Este documento |
