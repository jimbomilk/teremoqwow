# overlays/

Overlays HTML5 interactivos sincronizados con el vídeo (encuestas, estadísticas, publicidad no intrusiva).

- **Agente responsable**: [Player & Overlay](../.github/agents/player-overlay.agent.md).
- **Contratos**: [schemas/sync/v1/interaction-event.json](../schemas/sync/v1/interaction-event.json) (eventos del track MoQ `interaction`).
- **Boundary**: los overlays se ejecutan en un `<iframe sandbox="allow-scripts">` aislado del DOM del player; comunicación únicamente vía `postMessage`.

## Arquitectura

### Flujo de datos

```
[Servidor (Broadcast)] 
  ↓
[Track MoQ "interaction" + packaging "eventtimeline"]
  ↓
[Player: Watch.Net.Connection.subscribe("interaction")]
  ↓
[MoQWatch Web Component]
  ↓
[postMessage → iframe overlay]
  ↓
[Overlay renderiza (poll.html) y recolecta votos]
  ↓
[postMessage → Player]
  ↓
[Player: POST /interactions con voto]
  ↓
[Servidor: KrakenD /interactions endpoint]
```

### Seguridad

- **Sandbox**: `<iframe sandbox="allow-scripts">` **SIN** `allow-same-origin`
- **DOM**: El overlay **NO** puede acceder a `window.parent` ni al DOM del player
- **Mensajes**: Validación de `event.origin` en listeners `message`
- **Tokens**: El JWT no viaja en `postMessage`; el player hace la llamada HTTP autenticada

## Editor OpenOverlay (Integración)

### ¿Qué es OpenOverlay?

OpenOverlay es una herramienta web para crear overlays interactivos sin programar:
- **Visual editor** para diseñar templates HTML/CSS
- **Script builder** para lógica básica (mostrar/ocultar, cambiar colores, etc.)
- **Export** a paquete HTML autocontenido

### Flujo de integración

1. **Creador** abre OpenOverlay en la web (ej: `https://openoverlay.dev`)
2. **Diseña** el overlay (pregunta, opciones, estilos)
3. **Exporta** como `overlay.html` (HTML + CSS + JS inline, sin dependencias externas)
4. **Sube** a un servidor o empaqueta en el broadcast como track MoQ

### Publicación en MoQ

El paquete generado por OpenOverlay se publica como:

```json
{
  "namespace": "anon/live1",
  "trackName": "overlay_custom_1",
  "packaging": "eventtimeline",
  "payload": "<html>...exported HTML from OpenOverlay...</html>"
}
```

El player se suscribe vía:

```typescript
const subscription = connection.subscribe({
  namespace: "anon/live1",
  trackName: "overlay_custom_1",
});
```

### Contrato de mensajes

El overlay exportado por OpenOverlay **DEBE** implementar este protocolo:

#### Eventos recibidos (desde player → overlay vía `postMessage`)

```typescript
// Abrir encuesta
window.addEventListener('message', (event) => {
  if (event.data.type === 'interaction:poll_open') {
    const { question, options, duration_ms, poll_id } = event.data.data;
    // Renderizar encuesta
  }
});

// Actualizar conteos
if (event.data.type === 'interaction:stats_update') {
  const { counts } = event.data.data;
  // Actualizar barras de progreso
}

// Cerrar encuesta
if (event.data.type === 'interaction:poll_close') {
  const { winner_option_id, counts } = event.data.data;
  // Mostrar ganador y ocultar
}
```

#### Mensajes enviados (desde overlay → player vía `postMessage`)

```typescript
// Cuando el usuario vota
window.parent.postMessage({
  type: 'interaction:vote',
  data: {
    poll_id: '...',
    option_id: '...',
    timestamp: new Date().toISOString(),
  }
}, '*');
```

## Implementaciones actuales

### poll.html

Overlay de encuesta autocontenido (sin dependencias externas).

- **Responsabilidades**:
  - Recibe `interaction:poll_open` y renderiza pregunta + opciones
  - Recibe `interaction:stats_update` y actualiza barras de progreso en tiempo real
  - Recibe `interaction:poll_close` y muestra resultado
  - Envía votos via `postMessage` cuando el usuario click en opción

- **Seguridad**:
  - HTML/CSS/JS inline (no carga recursos externos)
  - No accede a `window.parent.document`
  - Usa `sandbox="allow-scripts"` (aislamiento completo)

- **Estilos**:
  - Dark theme (rgba(0, 0, 0, 0.85)) para no interferir con el vídeo
  - Animación suave al aparecer
  - Responsive (max-width: 90%)

## Estado

- Fase 4:
  - ✅ Sandbox de iframe (`allow-scripts` sin `allow-same-origin`)
  - ✅ poll.html template
  - ✅ Integración con track `interaction`
  - ✅ `postMessage` bidireccional
  - 📋 OpenOverlay editor (integración documentada, implementación externa)
  - 📋 Editor web integrado en `overlays/` (próxima fase si se requiere UI local)
