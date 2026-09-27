# config/

Configuración declarativa por servicio.

## Convenciones

- **12-factor**: la configuración vive en variables de entorno; los ficheros de este directorio son *plantillas* declarativas por servicio.
- **Jerarquía**: `env` > archivo de configuración > defaults del binario.
- **Secretos**: nunca en repo. Sólo placeholders en [`.env.example`](.env.example). Los reales viven en el gestor de secretos del entorno de despliegue.
- **Nombres**: `SCREAMING_SNAKE_CASE`, prefijo por servicio (`RELAY_`, `MEDIAMTX_`, `KRAKEND_`, `STRIPE_`, `EZDRM_`).

## Estructura prevista

- `.env.example` — plantilla de todas las variables.
- `mediamtx/` — configuración de MediaMTX (issue [#52](https://github.com/jimbomilk/teremoqwow/issues/52)).
- `srt-bond/` — bond SRT active-backup entre encoders y MediaMTX (issue [#53](https://github.com/jimbomilk/teremoqwow/issues/53)).
- `relay/` — configuración del relay (issue [#54](https://github.com/jimbomilk/teremoqwow/issues/54)).
- `krakend/` — configuración de KrakenD (issue [#55](https://github.com/jimbomilk/teremoqwow/issues/55)).
- `moq-mux/` — pipeline FFmpeg → moq-pub: transcodificación ABR 3 renditions + catálogo MoQ (issue [#56](https://github.com/jimbomilk/teremoqwow/issues/56)).
