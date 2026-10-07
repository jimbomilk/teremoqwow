# player/

**teremoqwow Player** — HTML5 video player con ultra-baja latencia basado en **Media over QUIC (MoQ)** y **WebCodecs**.

- **Agente responsable**: [Player & Overlay](../.github/agents/player-overlay.agent.md)
- **Contratos**: [schemas/media/](../schemas/media/), [schemas/sync/](../schemas/sync/), [schemas/drm/](../schemas/drm/)
- **Phase**: Phase 0-1 (Implementación en issues [#57](https://github.com/jimbomilk/teremoqwow/issues/57), [#60](https://github.com/jimbomilk/teremoqwow/issues/60))

> ✅ **Fase 1 - Actualización ABR**: Añadido controlador ABR con historial de 5 muestras, histeresis y selección automática de rendition (High/Medium/Low). Evento custom `moq:abr` + HUD con throughput estimado.
> ✅ **Fase 1 - Dependencias**: Actualizado a `@moq/watch@0.6.1` con API real (`Watch.Player`, `Watch.Net.Connection`, `Watch.Net.Path`). Los imports dinámicos permiten modular el cargador de dependencias.

## Arquitectura

```
┌─────────────┐
│ MoQ Relay   │ (https://relay:4443)
│ (moq-relay) │
└──────┬──────┘
       │ MoQ broadcast (teremoqwow/dev/live1)
       ↓
┌─────────────────────────────────┐
│  moq-watch Web Component        │
│  ├─ Catalogo                    │
│  ├─ VideoDecoder (WebCodecs)    │
│  ├─ Canvas render               │
│  └─ Latency metrics             │
└─────────────────────────────────┘
       │
       └─→ Custom Events
           ├─ moq:latency
           ├─ moq:error
           └─ moq:ready
```

## Phase 0-1 Scope

**Phase 0** (Issue #57):
- ✅ Web Component `<moq-watch>` con atributos `url`, `namespace`, `broadcast`
- ✅ Suscripción a catálogo MoQ (`catalog.json`)
- ✅ Selección de la primera rendition del selection_group `video-abr`
- ✅ Decodificación con `VideoDecoder` (WebCodecs)
- ✅ Renderizado en `<canvas>`
- ✅ Cálculo de latencia glass-to-glass (PTS vs wallclock)
- ✅ Eventos custom (`moq:latency`, `moq:error`, `moq:ready`)
- ✅ UI básica con estadísticas en directo

**Phase 1** (Issue #60):
- ✅ Controlador ABR (`src/abr.ts`) con historial de throughput
- ✅ Selección automática de rendition (video-high/medium/low)
- ✅ Histeresis adaptativa (up: 3000ms, down: 1000ms)
- ✅ Evento custom `moq:abr` con detalles de conmutación
- ✅ HUD visual (#abr-status) con rendition y throughput estimado
- ✅ Atributo `abr-window` configurable en Web Component

## Instalación y desarrollo

### Requisitos

- Node.js ≥ 18 (para WebCodecs support)
- npm o yarn

### Setup

```bash
cd player/
npm install
```

### Desarrollo local

```bash
npm run dev
```

Abre `http://localhost:5173` en tu navegador.

**Nota**: Para probar contra el relay de desarrollo (`https://relay:4443`), asegúrate de que:
- El relay está corriendo en `config/relay/relay.toml`
- El namespace `teremoqwow/dev/live1` está activo
- moq-mux está publicando broadcasts
- TLS/self-signed certs están configurados (permítelos en el navegador)

### Build

```bash
npm run build
```

Output en `dist/`.

### Preview

```bash
npm run preview
```

### Producción detrás de `/player/`

Vite genera referencias relativas (`./assets/...`) para que los assets funcionen tanto
con el servidor de desarrollo en `/` como con el build publicado bajo `/player/`.
El build de producción usa `https://wow.teremoq.com:4443/anon` con el broadcast
`anon/live1`, conectándose por WebTransport. El certificado público de Let's Encrypt
no requiere un `cert-hash`; el valor se deja vacío en el build. Para relays de desarrollo
con certificados autofirmados, configura el hash como se indica a continuación.

## Dependencias principales

| Paquete | Versión | Rol |
|---------|---------|-----|
| `@moq/watch` | `^0.6.1` | Player headless + API `Watch.Player`, `Watch.Net.Connection` |
| `@moq/signals` | `^0.2.5` | Reactive signals (`Signal`) para propiedades mutables |
| `typescript` | `^5.3.3` | Lenguaje |
| `vite` | `^5.0.8` | Build tool |

## Certificado autofirmado de dev (WebTransport)

Para conectarse al relay de desarrollo con cert autofirmado, obtén el SHA-256 fingerprint:

```bash
openssl x509 -in config/relay/certs/relay.pem -noout -fingerprint -sha256 | tr -d ':' | awk -F= '{print tolower($2)}'
```

Luego, edita en `index.html`:

```html
<canvas 
  id="moq-canvas" 
  data-url="https://127.0.0.1:4443/anon" 
  data-name="anon/live1" 
  data-cert-hash="<AQUÍ-PEGA-EL-HASH>"
>
</canvas>
```

El player validará el certificado contra el `cert-hash` usando `Watch.Net.Connection`.

## Controlador ABR (Adaptive Bitrate)

### Descripción

El controlador ABR implementa selección automática de rendition basada en un historial de **5 muestras de throughput** (configurable) con lógica de **histeresis** para evitar "flapping" (cambios muy frecuentes).

**Ubicación**: `src/abr.ts` (clase `AbrController`)

### Cómo funciona

1. **Muestreo de throughput**: Cada 2 segundos (aproximadamente, sincronizado con IDR frames de MoQ), se calcula el throughput actual en kbps y se añade al historial.

2. **Media móvil**: Se calcula la media de las últimas N muestras (default: 5).

3. **Selección de rendition**: Se elige la rendition óptima comparando el throughput suavizado con los umbrales definidos.

4. **Histeresis**: 
   - **Para subir** de calidad: el throughput debe estar por encima del threshold_up durante `hysteresisUp` ms (default: 3000ms).
   - **Para bajar** de calidad: el throughput debe caer por debajo del threshold_down durante `hysteresisDown` ms (default: 1000ms).
   - Esto previene cambios frecuentes y mejora la experiencia del usuario.

5. **Conmutación en fronteras de grupo MoQ**: El cambio de rendition se produce en límites de grupo MoQ (frames IDR), típicamente cada 2 segundos en nuestra configuración, nunca a mitad de un segmento.

### Renditions y umbrales (Fase 1)

| Rendition | Bitrate | threshold_up | threshold_down |
|-----------|---------|--------------|----------------|
| `video-high` | 2500 kbps | 4000 kbps | 3500 kbps |
| `video-medium` | 1200 kbps | 2500 kbps | 2000 kbps |
| `video-low` | 600 kbps | 0 kbps | 0 kbps |

**Notas**:
- `video-low` nunca se abandona por debajo (es el fallback).
- La selección comienza en `video-medium` por defecto.
- Los umbrales se basan en simulaciones de Fase 0 y QoS budget en [qos/latency-budget.md](../qos/latency-budget.md).

### Eventos y HUD

El player emite un evento custom `moq:abr` cuando cambia la rendition:

```typescript
element.addEventListener('moq:abr', (event: CustomEvent) => {
  const { from, to, throughput_kbps } = event.detail;
  console.log(`ABR: ${from} → ${to} (${throughput_kbps} kbps)`);
});
```

En `index.html`, existe un elemento `#abr-status` que muestra:
- **Símbolo de calidad**: 📶 High / Medium / Low (con color según rendition)
- **Throughput estimado**: en Mbps (ej: "4.2 Mbps")
- **Posición**: top-right sobre el canvas, con fondo semi-transparente

Ejemplo: `📶 High · 4.2 Mbps` (en verde para video-high)

### Configuración en el Web Component

Desde `index.html`, puedes configurar el tamaño de la ventana ABR:

```html
<moq-watch 
  url="https://127.0.0.1:4443/anon" 
  name="anon/live1" 
  abr-window="5"
  cert-hash="..."
>
</moq-watch>
```

- `abr-window`: número de muestras para la media móvil (default: 5).

Los tiempos de histeresis (`hysteresisUp`, `hysteresisDown`) son constantes en código (3000ms y 1000ms respectivamente). Para cambiarlos, edita `src/moq-watch.ts` en el método `init()`.

### Limitaciones y TODOs (Fase 1)

- ⚠️ **Throughput estimado**: Actualmente se calcula a partir del bitrate de la rendition actual, no de datos reales del decoder. En Fase 2, integraremos eventos del decoder para muestreo real.
- ⚠️ **API de conmutación**: `Watch.Player` v0.6.1 no expone API directa para cambiar rendition. En Fase 2, o bien:
  - Esperamos una nueva versión de `@moq/watch` con API de track selection.
  - O implementamos una suscripción paralela a múltiples tracks y switcheamos entre ellas.
- ✅ **Histeresis adaptativa**: Implementada como timestamps, predecible.

## WebCodecs support

El player requiere **WebCodecs** para decodificación:

- **Chrome/Edge**: ✅ Soportado (v94+)
- **Firefox**: ⚠️ Desactivado por defecto (habilitar `dom.media.webcodecs.enabled`)
- **Safari**: ✅ Soportado (v16.4+)

Si WebCodecs no está disponible, el player emitirá un evento `moq:error`.

## Roadmap Phase 0 → Phase 3

### Phase 0: Player Básico ✅ (Issue #57)
- Web Component con un track (video-high)
- Latencia glass-to-glass
- Estadísticas básicas

### Phase 1: ABR Selector ✅ (Issue #60, Ola 2)
- ✅ Controlador ABR con historial de throughput (5 muestras)
- ✅ Selección automática High/Medium/Low según umbrales
- ✅ Histeresis para evitar flapping
- ✅ Evento custom `moq:abr` + HUD con throughput
- ⏳ Integración real de datos de decoder (Fase 1b)
- ⏳ API de conmutación de track en Watch.Player (pending v0.7.0)

### Phase 2: Overlays (Issue #59, est. 5pt)
- iframe sandbox para overlays HTML5
- OpenOverlay editor integration
- Sincronización de eventos vs PTS

### Phase 3: DRM & Monetización (future)
- Integración EZDRM
- License requests
- Stripe billing hooks

## Arquitectura interna

### `src/moq-watch.ts`

Web Component principal:
- `connectedCallback()`: Inicializa conexión MoQ
- `fetchCatalog()`: Lee `{namespace}/catalog` vía MoQ
- `initDecoder()`: Configura `VideoDecoder` con el codec del track
- `subscribeToTracks()`: Se suscribe a init + video tracks
- `renderFrame()`: Dibuja frames en canvas, emite latencia

### `src/latency.ts`

Helpers para calcular latencia glass-to-glass:
- `estimateNTPOffset()`: Calcula offset entre reloj local y NTP del servidor
- `calculateLatency()`: Estima latencia como `(now - pts) - offset_ntp`
- `formatLatency()`: Formatea para display

**Aproximación Phase 0**:
- Asumimos que el catálogo proporciona `created_at.wallclock_ns` (timestamp NTP absoluto)
- Estimamos el offset al conectar
- En cada frame, usamos `VideoFrame.timestamp` (en microsegundos) para calcular la latencia actual

**Precisión esperada**: ±50ms (mejorará con sincronización NTP real en Phase 1)

### `src/main.ts`

Entry point. Registra listeners de eventos custom del player y los loguea.

## Testing

### Verificación de latencia < 700ms

```bash
# Abre index.html en navegador contra https://relay:4443/
# Observa las estadísticas en directo:
#   - Latencia glass-to-glass
#   - Frames decodificados
#   - Codec activo
```

### Debugging

En DevTools:
```javascript
// Escucha eventos
document.querySelector('moq-watch').addEventListener('moq:latency', e => {
  console.log('Latency:', e.detail.latency_ms, 'ms');
});
```

## Notas técnicas

1. **Cross-browser WebCodecs**: Phase 0 asume Chrome/Edge/Safari. Firefox requiere habilitar flag.
2. **Codec real**: Phase 0 usa `avc1.4D4028` (H.264). Phase 1 puede soportar VP9/AV1 si el relay lo provee.
3. **Latencia**: Es una aproximación. Phase 1 usará sincronización NTP real + SFU metrics.
4. **Sandbox overlay**: El iframe del overlay NO tendrá `allow-same-origin` para aislar del DOM del player.

## Referencias

- [MoQ RFC 9546](https://datatracker.ietf.org/doc/html/rfc9546)
- [WebCodecs API](https://www.w3.org/TR/webcodecs/)
- [Architecture](../docs/architecture.md)
- [Schemas](../schemas/)
