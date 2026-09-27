# player/

**teremoqwow Player** — HTML5 video player con ultra-baja latencia basado en **Media over QUIC (MoQ)** y **WebCodecs**.

- **Agente responsable**: [Player & Overlay](../.github/agents/player-overlay.agent.md)
- **Contratos**: [schemas/media/](../schemas/media/), [schemas/sync/](../schemas/sync/), [schemas/drm/](../schemas/drm/)
- **Phase**: Phase 0 (Implementación en issue [#57](https://github.com/jimbomilk/teremoqwow/issues/57))

> **TODO Fase 0.1**: la dependencia `@kixelated/moq` se declara como estándar de facto; verificar el paquete real y su API (`MoQClient`, suscripción a catálogo) antes de `npm install`. Si el nombre/versión del cliente MoQ para JS/TS difiere, ajustar `package.json` y los imports en `src/moq-watch.ts`.

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

## Phase 0 Scope

- ✅ Web Component `<moq-watch>` con atributos `url`, `namespace`, `broadcast`
- ✅ Suscripción a catálogo MoQ (`catalog.json`)
- ✅ Selección de la primera rendition del selection_group `video-abr`
- ✅ Decodificación con `VideoDecoder` (WebCodecs)
- ✅ Renderizado en `<canvas>`
- ✅ Cálculo de latencia glass-to-glass (PTS vs wallclock)
- ✅ Eventos custom (`moq:latency`, `moq:error`, `moq:ready`)
- ✅ UI básica con estadísticas en directo

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

## Dependencias principales

| Paquete | Versión | Rol |
|---------|---------|-----|
| `@kixelated/moq` | `^0.2.0` | Cliente MoQ (suscripción a tracks) |
| `typescript` | `^5.3.3` | Lenguaje |
| `vite` | `^5.0.8` | Build tool |

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

### Phase 1: ABR Selector (Issue #58, est. 3pt)
- UI para elegir High/Medium/Low
- Cambio dinámico de track
- QoS feedback

### Phase 2: Overlays (Issue #59, est. 5pt)
- iframe sandbox para overlays HTML5
- OpenOverlay editor integration
- Sincronización de eventos vs PTS

### Phase 3: DRM & Monetización (Issue #60, est. 8pt)
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
