# config/krakend/

Configuración de **KrakenD API Gateway (Community Edition)** para teremoqwow.

- **Agente responsable**: Arquitecto
- **Issue**: [#55 — Fase 0: Configurar KrakenD API Gateway Base](https://github.com/jimbomilk/teremoqwow/issues/55)
- **Contratos**: [schemas/api/v1/](../../schemas/api/v1/) · [schemas/registry/v1/registry-join.json](../../schemas/registry/v1/registry-join.json)

## Puertos

| Puerto | Uso |
|---|---|
| `8080` | HTTP público del gateway |
| `9090` | Métricas Prometheus (namespace `teremoqwow`) |

## Endpoints iniciales

| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Liveness probe estático. Responde `{"status":"ok"}`. |
| `POST` | `/registry/join` | Alta/renovación de nodo relay. Body validado contra [`schemas/registry/v1/registry-join.json`](../../schemas/registry/v1/registry-join.json). Proxied a `registry:8081/v1/registry/join`. |

## Arrancar con Docker

```bash
docker run --rm -it \
  -p 8080:8080 \
  -p 9090:9090 \
  -v "$(pwd)/config/krakend/krakend.json:/etc/krakend/krakend.json:ro" \
  -v "$(pwd)/schemas:/etc/krakend/schemas:ro" \
  devopsfaith/krakend:2.10 \
  run -c /etc/krakend/krakend.json
```

> Los esquemas se montan bajo `/etc/krakend/schemas` para que el plugin `validation/json-schema` los resuelva mediante `file:///`.

## Verificación

```bash
# Health
curl -s http://127.0.0.1:8080/health | jq .
# → {"status":"ok","service":"teremoqwow-gateway"}

# Métricas Prometheus
curl -s http://127.0.0.1:9090/metrics | grep teremoqwow

# Validación (debe rechazar body inválido con 400)
curl -X POST http://127.0.0.1:8080/registry/join \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer dev" \
  -d '{}'
```

## Observabilidad

- **Prometheus**: expuesto en `:9090` con etiquetas `host`, `path`, `method`, `statuscode`.
- **OpenTelemetry**: exporter OTLP configurado hacia `otel-collector:4317` (gRPC). Sampling 10%.

## Notas de diseño

- `validation/json-schema` usa Draft 7 en la versión CE actual de KrakenD; los schemas de teremoqwow están en Draft 2020-12. Cuando KrakenD amplíe soporte a 2020-12, se eliminarán conversiones puntuales. Los stubs actuales son compatibles con ambos drafts.
- `/health` es estático (`backend/static`) para no depender de ningún upstream; refleja únicamente que el gateway está vivo.
- Los upstreams reales (`http://registry:8081`) todavía no existen: son placeholders que se conectarán en issues posteriores.

## Fuera de alcance

- Endpoints para `interaction-create`, `qos-report`, DRM, telemetría → issues específicas de Fase 1.
- Rate limiting, circuit breaker, JWT enforcement → issues posteriores.
