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
