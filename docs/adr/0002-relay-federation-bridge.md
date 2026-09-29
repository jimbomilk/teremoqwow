# 0002 - Estrategia de federación entre relays: bridge temporal vs clustering nativo

- **Estado**: Aceptado
- **Fecha**: 2026-09-29
- **Deciden**: @jimbomilk

## Contexto

La Fase 6 requiere que los broadcasts se propaguen entre dos instancias de `moq-relay`
para servir a espectadores en distintas regiones sin conectarse todos al nodo origen.

Al intentar configurar clustering con `moqdev/moq-relay:0.15.7` se descubrió que:
- El binario Docker no expone flags de clustering en tiempo de ejecución (`configured=false`)
- El relay ignora `--connect` (ese flag es del CLI `moq`, no del relay)
- El `relay.toml` que lee la configuración `[cluster.connect]` es el del binario compilado
  desde fuente, no el nuestro en `config/relay/relay.toml`

Evidencia: `cluster initialized hop_id=... configured=false — no cluster peers configured; running standalone`

## Decisión

Adoptar una estrategia en **dos fases**:

### Fase actual (bridge)
Usar un contenedor `moq` cliente como bridge entre relays:

```
Publisher → relay-1 (EU)
               ↓
         bridge container
         (moq export ts | moq import ts)
               ↓
           relay-2 (US)
               ↓
         Subscriber (US)
```

El bridge suscribe el namespace completo en relay-1 y lo re-publica en relay-2.
Añade ~50ms de latencia por hop y requiere un bridge por namespace activo.

### Fase producción (clustering nativo)
Compilar `moq-rs` desde fuente con la configuración de peers en el `relay.toml` nativo
del binario, que sí soporta la sección `[cluster]`:

```toml
[cluster]
node = "relay-eu-west-1"
[[cluster.connect]]
url = "https://relay-us-east-1.teremoqwow.dev"
```

O esperar que `moqdev/moq-relay` publique una imagen con soporte CLI para clustering.

## Consecuencias

**Positivas**:
- El bridge funciona hoy con los binarios disponibles sin recompilar
- Permite validar el caso de uso de propagación multi-relay
- El diseño de contratos (`/registry/join`, `cluster.jwt`) no cambia entre bridge y clustering nativo

**Negativas / trade-offs**:
- El bridge añade ~50ms de latencia por hop de relay
- No escala automáticamente a nuevos namespaces (requiere un bridge por namespace)
- En producción necesitará ser reemplazado por clustering nativo

**Neutras**:
- Los schemas `schemas/registry/v1/` son válidos para ambas estrategias
- El endpoint `/registry/join` emite el mismo `cluster.jwt` en ambos casos

## Alternativas consideradas

- **Solo clustering nativo** — descartado porque requiere compilar `moq-rs` desde fuente
  (no hay imagen Docker disponible con esta capacidad en la versión 0.15.7).
- **Actualizar a moq-relay con draft-18** — descartado por incompatibilidad de protocolo
  con el resto del stack (moq-lite-06). Ver ADR-0001.
- **Un único relay sin federación** — descartado porque no cumple el requisito de escala
  geográfica del roadmap.
