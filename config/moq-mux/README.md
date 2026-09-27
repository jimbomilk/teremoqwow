# config/moq-mux/

Configuración del pipeline de ingestión SRT basado en **`moq import srt` + FFmpeg**
(CLI unificado [`moqdev/moq`](https://github.com/moqdev/moq) 0.12.7).
Issue: [#56](https://github.com/jimbomilk/teremoqwow/issues/56) · [#116](https://github.com/jimbomilk/teremoqwow/issues/116).

> **Cambio desde issue #116**: `moq-pub` como binario standalone no existe en
> `moqdev/moq 0.12.7`. El subcomando `moq import srt --listen` reemplaza el pipe
> `FFmpeg → moq-pub`. MediaMTX ya no es intermediario en este tramo.

---

## Objetivo

Recibir señal SRT, publicarla en el relay MoQ bajo el namespace `anon/live1`
para que el player pueda consumirla vía MoQ/QUIC.

> **Namespace `anon/`**: el relay autoriza sin credenciales el subtree `anon/**`
> (flag `--auth-public 'anon/**'` en `relay.toml`). **No usar** `teremoqwow/dev/live1`
> como broadcast; ese subtree no está autorizado en modo público.

---

## Diagrama

```
  SRT source (broadcast encoder o FFmpeg dev/test)
        │  SRT publish → srt://127.0.0.1:8890?streamid=publish:live1
        ▼
┌──────────────────────────────────────────────────┐
│  moq import srt                                  │
│  --listen [::]:8890  --latency 200ms             │
│  --connect tcp://relay:4444/anon                 │
│  --broadcast anon/live1                          │
└─────────────────────────┬────────────────────────┘
                          │  MoQ / TCP (QUIC en prod)
                          ▼
                 relay:4444  (moqdev/moq relay)
```

---

## Dependencias

| Componente | Versión mínima | Notas |
|---|---|---|
| FFmpeg | 6.0 | Con `libx264`, `libsrt`, `libaac` |
| moq CLI | 0.12.7 | `moqdev/moq` — subcomando `import srt` |

---

## Variables de entorno

| Variable | Default | Descripción |
|---|---|---|
| `MOQ_RELAY_TCP` | `tcp://relay:4444/anon` | Endpoint TCP del relay MoQ |
| `MOQ_BROADCAST` | `anon/live1` | Broadcast path (debe estar bajo `anon/**`) |
| `SRT_LISTEN_ADDR` | `[::]:8890` | Dirección en la que el listener SRT escucha |
| `SRT_LATENCY` | `200ms` | Latencia SRT del listener |

---

## Levantar el pipeline

```bash
# Arrancar listener SRT + FFmpeg de prueba (fuente sintética dev/test):
bash config/moq-mux/run.sh

# O con variables personalizadas (source SRT externo en producción):
MOQ_RELAY_TCP=tcp://relay:4444/anon \
MOQ_BROADCAST=anon/live1 \
SRT_LISTEN_ADDR=[::]:8890 \
SRT_LATENCY=200ms \
bash config/moq-mux/run.sh
```

El script:
1. Arranca `moq import srt --listen` en background como receptor SRT.
2. Arranca FFmpeg (fuente sintética en dev; source SRT externo en prod) que publica en ese listener.
3. Registra un trap SIGTERM/SIGINT para terminar ambos procesos limpiamente.

### Con Docker

```dockerfile
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*
COPY --from=moqdev/moq:0.12.7 /usr/local/bin/moq /usr/local/bin/moq
COPY config/moq-mux/run.sh /run.sh
ENTRYPOINT ["bash", "/run.sh"]
```

```bash
docker run --rm \
  -e MOQ_RELAY_TCP=tcp://relay:4444/anon \
  -e MOQ_BROADCAST=anon/live1 \
  -p 8890:8890/udp \
  --network teremoqwow_net \
  teremoqwow/moq-import:local
```

---

## Alineación SPS/PPS para ABR

Para que el player ABR (Fase 1, issue #60) pueda conmutar entre calidades sin
reinicializar el decoder, los tres streams de vídeo deben compartir la misma
estructura SPS/PPS. Esto requiere un perfil H.264 idéntico y GOP síncronos.

### Perfil `main` en los tres streams

El perfil H.264 determina el conjunto de herramientas de codificación. Si las
tres calidades usan perfiles distintos (p.ej. `baseline` vs `high`), el decoder
debe reinicializarse al conmutar, causando fotograma negro o corrupción visual.
Con `main` en los tres, sólo varía el `level_idc` (límites de resolución/bitrate)
y el decoder reutiliza la misma inicialización:

| Calidad | Resolución | Level H.264 | Codec string  |
|---------|------------|-------------|---------------|
| High    | 1280×720   | 4.0         | `avc3.4D4028` |
| Medium  | 854×480    | 3.1         | `avc3.4D401F` |
| Low     | 640×360    | 3.0         | `avc3.4D401E` |

### Por qué `-sc_threshold 0` es crítico

Sin esta flag, libx264 inserta IDRs adicionales ante cambios bruscos de escena.
Si ese IDR ocurre sólo en una calidad (porque el umbral de detección varía por
resolución), los GOP quedan desalineados. Al conmutar de calidad en un punto que
no es IDR en el stream de destino, el decoder produce artefactos o corrupción.

`-sc_threshold 0` desactiva la detección de escena: el único origen de IDRs es
`-force_key_frames "expr:gte(t,n_forced*2)"`, exactamente cada 2 s en los tres
streams simultáneamente.

### Comando de verificación SPS/PPS

```bash
ffprobe -v quiet -show_streams -of json <fichero.mp4> \
  | jq '.streams[] | select(.codec_type=="video") | {codec_name, profile, level}'
```

El resultado esperado para cada stream es `"profile": "Main"` con levels `40`,
`31` y `30` (FFprobe representa level como entero: 40 = 4.0, 31 = 3.1, 30 = 3.0).

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
# Inspeccionar keyframes desde el listener SRT local (dev/test):
ffprobe -v quiet -select_streams v:0 \
  -show_frames -of csv \
  -i "srt://127.0.0.1:8890?streamid=read:live1" \
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
| Ingestión SRT | **`moq import srt --listen`** | `moq-pub` no existe en `moqdev/moq 0.12.7`; el subcomando unificado elimina MediaMTX como intermediario |
| Namespace | **`anon/live1`** | El relay autoriza `anon/**` sin credenciales; otros subtrees requieren auth explícita |
| Source en dev/test | FFmpeg `testsrc2 + sine` | Fuente sintética reproducible; en prod sustituir por source SRT externo |
| Config TOML vs script | **run.sh** | `moq` no acepta config TOML; script parametrizable por env vars |

---

## Archivos en este directorio

| Fichero | Descripción |
|---|---|
| `run.sh` | Listener `moq import srt` + FFmpeg de prueba, parametrizado por env vars |
| `example-catalog.json` | Catálogo MoQ de referencia con los tracks esperados |
| `README.md` | Este documento |
