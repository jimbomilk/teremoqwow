# config/mediamtx/

Configuración de **MediaMTX** para recibir señal Broadcast por SRT.
Implementa la issue [#52](https://github.com/jimbomilk/teremoqwow/issues/52).

## Puertos expuestos

| Puerto | Protocolo | Uso |
|--------|-----------|-----|
| `8890` | UDP | SRT listener (ingesta + lectura) |
| `9997` | TCP | API HTTP de control |
| `9998` | TCP | Métricas Prometheus |

## Arrancar con Docker

Ejecutar desde la raíz del repositorio:

```bash
docker run --rm -it \
  -p 8890:8890/udp \
  -p 9997:9997 \
  -p 9998:9998 \
  -v "$(pwd)/config/mediamtx/mediamtx.yml:/mediamtx.yml:ro" \
  bluenviron/mediamtx:latest
```

> SRT usa UDP; asegúrate de exponer el puerto con `/udp` en el mapeo de Docker.

## Publicar señal SRT de prueba (FFmpeg)

```bash
ffmpeg -re \
  -f lavfi -i testsrc=size=1280x720:rate=30 \
  -c:v libx264 -preset ultrafast -tune zerolatency -g 60 \
  -f mpegts 'srt://127.0.0.1:8890?streamid=publish:live-main'
```

Para el path de backup, sustituir `live-main` por `live-backup`.

## Verificar reproducción con ffplay

```bash
ffplay 'srt://127.0.0.1:8890?streamid=read:live-main'
```

## API HTTP de control

Listar paths activos:

```bash
curl -s http://127.0.0.1:9997/v3/paths/list | jq .
```

Consultar un path concreto:

```bash
curl -s http://127.0.0.1:9997/v3/paths/get/live-main | jq .
```

## Métricas Prometheus

```bash
curl -s http://127.0.0.1:9998/metrics
```

Las métricas relevantes incluyen `mediamtx_path_readers_total` y `mediamtx_path_sources_total`.

## Notas de diseño

- RTSP, RTMP, HLS y WebRTC están **deshabilitados** intencionalmente; en esta fase solo se necesita SRT.
- El `streamid` SRT determina el path de destino: `publish:<path>` para publicar, `read:<path>` para leer.
- No se configuran credenciales en esta fase; la autenticación se abordará en una issue posterior siguiendo la política de secretos del repo (`config/.env.example`).
