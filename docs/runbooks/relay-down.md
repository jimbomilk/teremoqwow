# Runbook: Relay MoQ caído

**Severidad**: P1  
**SLO afectado**: Disponibilidad ≥ 99.99 %  
**RTO objetivo**: < 60 s

## Síntomas

- Alertas Site24x7 en `/health` con estado DOWN.
- Players sin vídeo / error `ERR_CONNECTION_REFUSED` en consola.
- Métrica `moq_relay_active_connections` = 0 en Grafana.

## Diagnóstico rápido

```bash
# 1. Verificar estado del contenedor
docker inspect moq-relay --format '{{.State.Status}}'

# 2. Ver últimas líneas de log
docker logs --tail 50 moq-relay

# 3. Comprobar puerto QUIC/TCP
ss -tlnp | grep 4443
```

## Pasos de recuperación

1. **Reinicio suave** (< 30 s RTO esperado):
   ```bash
   docker restart moq-relay
   sleep 5 && curl -sf http://localhost:8090/health || echo "KO"
   ```

2. **Si el contenedor no arranca** — revisar logs de error y recrear:
   ```bash
   docker rm -f moq-relay
   # Lanzar con el comando de la tarea "QoS: Levantar pipeline"
   # o ejecutar: bash config/relay/README.md → sección "Inicio rápido"
   ```

3. **Verificar certificados TLS** (causa frecuente de fallo al arrancar):
   ```bash
   openssl x509 -in /tmp/teremoqwow-e2e/certs/relay.pem -noout -dates
   # Si caducado: bash scripts/renew-dev-certs.sh
   ```

4. **Failover al peer federado** (si existe nodo secundario):
   - Actualizar DNS/load-balancer para apuntar al relay peer.
   - Notificar al canal `#alertas-produccion` con ETA de recuperación.

5. **Validar federación** tras restaurar:
   ```bash
   bash scripts/verify-federation.sh
   ```

## Escalado

- > 60 s sin resolución → escalar a on-call vía PagerDuty.
- > 5 min → activar modo degradado: servir VOD desde CDN.

## Post-mortem

Abrir issue en GitHub con etiqueta `incident` y plantilla ADR si el fallo revela un gap arquitectónico.
