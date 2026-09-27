# srt-bond — Redundancia SRT Active-Backup

## Objetivo

Recibe dos flujos SRT redundantes de encoders externos y presenta **una sola salida** hacia MediaMTX (`live-main`), implementando failover automático ante la caída del enlace principal.

## Diagrama

```
encoder-a ──SRT :8891──► ┐
                          ├─ srt-bond ──SRT :8890──► MediaMTX (live-main)
encoder-b ──SRT :8892──► ┘  (active-backup)
```

## Estrategia de bonding

Patrón **active-backup secuencial** implementado en [`bond.sh`](bond.sh):

1. El bond escucha en `:8891` (enlace primario). Cuando `encoder-a` se conecta, el flujo se reenvía a `srt://mediamtx:8890?streamid=publish:live-main`.
2. Si el enlace primario cae (`srt-live-transmit` termina), el bond conmuta automáticamente a `:8892` (enlace de respaldo) manteniendo la misma salida `live-main`.
3. Si el respaldo también cae, el ciclo regresa al primario.

La herramienta subyacente es **`srt-live-transmit`** (paquete `srt` en Alpine Linux), envuelta en `bond.sh` para gestionar la conmutación. No requiere imagen custom ni daemon externo.

> **¿Por qué no una imagen dedicada de srt-bond-relay?**
> No existe una imagen Docker oficial estable de `srt-bond-relay`. Haivision's `srt-xtransmit` está disponible como código fuente y requiere compilación con opciones específicas para bonding de grupos (`SRTO_GROUPCONNECT`, disponible en `libsrt >= 1.5`). Para Phase 0, `srt-live-transmit` + un script de supervisión ofrece el mismo comportamiento con dependencias mínimas y máxima transparencia. En producción puede sustituirse por `srt-xtransmit` compilado con soporte de grupos SRT o Haivision SRT Hub.

## Puertos

| Puerto (UDP) | Rol |
|---|---|
| `:8891` | Entrada primaria — encoder-a → bond |
| `:8892` | Entrada de respaldo — encoder-b → bond |
| `:8890` | Salida hacia MediaMTX (SRT, gestionado por MediaMTX) |

## Despliegue

```bash
# Desde la raíz del repo
docker compose -f config/srt-bond/docker-compose.yml up -d

# Estado de los servicios
docker compose -f config/srt-bond/docker-compose.yml ps

# Logs del bond en tiempo real
docker compose -f config/srt-bond/docker-compose.yml logs -f srt-bond
```

## Simular failover y verificar

### 1. Arrancar el stack

```bash
docker compose -f config/srt-bond/docker-compose.yml up -d
docker compose -f config/srt-bond/docker-compose.yml logs -f srt-bond
```

El log mostrará:
```
[bond][...] ACTIVE PRIMARY :8891 -> mediamtx:8890/live-main
```

### 2. Provocar caída del encoder principal

```bash
docker compose -f config/srt-bond/docker-compose.yml stop encoder-a
```

El log del bond mostrará:
```
[bond][...] PRIMARY :8891 ended (exit=1)
[bond][...] Primary link dropped. Switching to BACKUP :8892
[bond][...] ACTIVE BACKUP :8892 -> mediamtx:8890/live-main
```

### 3. Verificar que live-main sigue con publisher

```bash
curl -s http://localhost:9997/v3/paths/list | \
  jq '.items[] | select(.name=="live-main") | {name, ready, tracks: (.tracks | length)}'
```

El path `live-main` debe aparecer como `ready: true` con tracks activos.

### 4. Comprobar distinción visual del failover

Conectar un reproductor SRT al path `live-main`:
```bash
ffplay "srt://localhost:8890?streamid=read:live-main&latency=200"
```

El borde **rojo** indica señal de `encoder-a` (primario); el borde **azul** indica señal de `encoder-b` (backup).

### 5. Recuperar el enlace principal

```bash
docker compose -f config/srt-bond/docker-compose.yml start encoder-a
```

El bond volverá al primario en el siguiente ciclo (tras la caída natural del backup o reiniciando el bond):
```bash
docker compose -f config/srt-bond/docker-compose.yml restart srt-bond
```

## Variables de entorno

Definidas en [`srt-bond.conf`](srt-bond.conf) y cargadas por `docker-compose.yml` vía `env_file`.

| Variable | Default | Descripción |
|---|---|---|
| `PRIMARY_PORT` | `8891` | Puerto de escucha del enlace primario |
| `BACKUP_PORT` | `8892` | Puerto de escucha del enlace de respaldo |
| `MEDIAMTX_HOST` | `mediamtx` | Hostname de MediaMTX (DNS Docker) |
| `MEDIAMTX_PORT` | `8890` | Puerto SRT de MediaMTX |
| `MEDIAMTX_PATH` | `live-main` | Path de publicación en MediaMTX |
| `SRT_LATENCY_MS` | `200` | Latencia SRT end-to-end en ms |
| `RECONNECT_DELAY_S` | `1` | Pausa entre reintentos tras caída de ambos enlaces |

## Limitaciones conocidas (Phase 0)

- **Failover activo solo cuando el enlace estaba activo**: si `encoder-a` nunca se conecta (estaba caído al arrancar el bond), el bond queda bloqueado esperando en listener mode en `:8891`. Para forzar el salto al backup: `docker compose restart srt-bond`.
- **Regreso al primario no es automático**: tras una caída de ambos enlaces, el bond vuelve al primario. Si el primario sigue caído, queda bloqueado de nuevo. Esto se resolverá en Phase 1 con un watchdog que consulte la API de MediaMTX (`:9997/v3/paths/list`) y fuerce la rotación.
- **Una conexión simultánea por puerto**: `srt-live-transmit` en listener mode acepta solo una conexión. Si dos encoders intentan conectarse al mismo puerto, el segundo es rechazado.

## Hoja de ruta

| Fase | Mejora |
|---|---|
| Phase 1 | Watchdog que consulta API MediaMTX y fuerza failover proactivo por métricas (RTT, pérdida de paquetes) |
| Phase 2 | Migrar a `srt-xtransmit` con `SRTO_GROUPCONNECT` para verdadero bonding active-active con agregación de ancho de banda |
