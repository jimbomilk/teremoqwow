import { estimateNTPOffset, calculateLatency, formatLatency } from './latency.ts';
import { AbrController, DEFAULT_RENDITIONS, type Rendition } from './abr.ts';
import { OverlaySyncScheduler, type TimingDeviation } from './overlay-sync.ts';
import { OverlayEngine } from './overlay-engine.ts';

/** Fetches cert hash from KrakenD /cert-hash, falling back to a provided getter. */
export async function fetchCertHash(
  getCertHashAttr: () => string | null,
): Promise<string | null> {
  try {
    const r = await fetch('/cert-hash');
    if (r.ok) {
      const d = await r.json();
      if (d.cert_hash) return d.cert_hash;
    }
  } catch (_) {}
  return getCertHashAttr() || null;
}

/**
 * moq-watch Web Component (Headless Player)
 *
 * Implementa la API real de @moq/watch@0.6.1 con Watch.Player + Watch.Net.Connection
 *
 * Attributes:
 *   - url: MoQ relay URL (default: "https://127.0.0.1:4443/anon")
 *   - name: Broadcast name (default: "anon/live1")
 *   - cert-hash: SHA-256 hex del cert del relay (opcional, para WebTransport self-signed)
 *   - abr-window: Tamaño de ventana ABR (default: "5")
 *
 * Events:
 *   - moq:ready: cuando el player está listo
 *   - moq:error: {message} cuando ocurre un error
 *   - moq:latency: {latency_ms, pts_ms, render_ts_ms, ntp_offset_ms}
 *   - moq:abr: {from, to, throughput_kbps} cuando cambia la rendition
 */
/**
 * Interfaz para mensajes postMessage entre player e overlay
 */
interface OverlayMessage {
  type: string;
  data?: any;
  payload?: any;
}

/**
 * Interfaz para eventos de interacción (del track MoQ)
 */
interface InteractionEvent {
  id: string;
  kind: 'poll_open' | 'poll_close' | 'stats_update';
  timestamp: any;
  poll_id: string;
  question?: string;
  duration_ms?: number;
  options?: Array<{ id: string; text: string }>;
  counts?: { [optionId: string]: number };
  winner_option_id?: string;
}

// ─── Exported pure logic (no DOM dependency — importable in Node tests) ───────

export type PlayerState = 'connecting' | 'live' | 'error' | 'unavailable';

/** Builds the shadow-DOM HTML for the moq-watch component. Exported for testing. */
export function buildShadowHtml(isEmbed: boolean): string {
  const overlayClass = isEmbed ? 'status-connecting embed' : 'status-connecting';
  const hudClass = isEmbed ? 'hud-visible' : 'hud-hidden';
  return `<style>
      :host {
        display: block; width: 100%; aspect-ratio: 16 / 9;
        background: #000; border-radius: 8px; overflow: hidden; position: relative;
      }
      canvas { width: 100%; height: 100%; display: block; object-fit: contain; }
      #overlay-container {
        position: absolute; top: 0; left: 0; width: 100%; height: 100%;
        pointer-events: none; z-index: 10;
      }
      #overlay-container iframe { width: 100%; height: 100%; border: none; pointer-events: auto; }
      #status-overlay {
        position: absolute; inset: 0;
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        background: rgba(0,0,0,0.75); color: #fff; z-index: 20; gap: 12px;
        transition: opacity 1s;
      }
      #status-overlay.status-live { opacity: 0; pointer-events: none; }
      @keyframes spin { to { transform: rotate(360deg); } }
      .status-spinner {
        width: 36px; height: 36px;
        border: 3px solid rgba(255,255,255,0.3); border-top-color: #fff;
        border-radius: 50%; animation: spin 0.8s linear infinite;
      }
      .status-live .status-spinner,
      .status-error .status-spinner,
      .status-unavailable .status-spinner { display: none; }
      .status-text { font-size: 14px; text-align: center; }
      .status-retry {
        padding: 6px 16px; background: #ef5350; border: none;
        border-radius: 4px; color: #fff; cursor: pointer; font-size: 13px; display: none;
      }
      .status-error .status-retry,
      .status-unavailable .status-retry { display: block; }
      #status-overlay.embed .status-text { font-size: 11px; }
      #hud {
        position: absolute; bottom: 8px; right: 8px;
        background: rgba(0,0,0,0.65); color: #fff; font-size: 11px;
        padding: 3px 8px; border-radius: 4px; font-family: monospace;
        transition: opacity 0.2s; pointer-events: none; z-index: 15;
      }
      .hud-hidden { opacity: 0; }
      .hud-visible { opacity: 1; }
      .hud-latency-warn { color: #ef5350; }
      .hud-sep { margin: 0 4px; opacity: 0.5; }
    </style>
    <canvas width="1280" height="720"></canvas>
    <div id="status-overlay" class="${overlayClass}">
      <div class="status-spinner"></div>
      <div class="status-text">Conectando al relay\u2026</div>
      <button class="status-retry">\u21ba Reintentar</button>
    </div>
    <div id="hud" class="${hudClass}">
      <span id="hud-quality">\u2014</span>
      <span class="hud-sep">|</span>
      <span id="hud-latency">\u2014 ms</span>
    </div>
    <div id="overlay-container"></div>`;
}

/** Pure player state machine — no DOM dependency. */
export class PlayerLogic {
  state: PlayerState = 'connecting';
  reconnectAttempt = 0;
  reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  readonly BACKOFF_MS: readonly number[] = [2000, 5000, 10000, 30000, 60000];
  viewerToken: string | null = null;

  handleReady(): void {
    this.state = 'live';
    this.reconnectAttempt = 0;
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  handleError(scheduleTimeout: (delay: number) => ReturnType<typeof setTimeout>): void {
    if (this.reconnectAttempt >= this.BACKOFF_MS.length) {
      this.state = 'unavailable';
      return;
    }
    this.state = 'error';
    const delay = this.BACKOFF_MS[this.reconnectAttempt++];
    this.reconnectTimer = scheduleTimeout(delay);
  }

  cleanup(): void {
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }

  async acquireToken(fetchImpl: typeof fetch = fetch): Promise<void> {
    try {
      const r = await fetchImpl('/auth/token-anonymous', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
      });
      if (r.ok) {
        const d = await r.json();
        this.viewerToken = (d as any).access_token ?? null;
      }
    } catch (_) {}
  }

  async submitVote(
    voteData: unknown,
    broadcastName: string,
    fetchImpl: typeof fetch = fetch,
  ): Promise<boolean> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (this.viewerToken) {
      headers['Authorization'] = `Bearer ${this.viewerToken}`;
    }
    try {
      const r = await fetchImpl('/interactions', {
        method: 'POST',
        headers,
        body: JSON.stringify({ broadcast: broadcastName, kind: 'vote', payload: voteData }),
      });
      return r.ok;
    } catch (_) {
      return false;
    }
  }
}

/** Pure HUD state — no DOM dependency. */
export class HudState {
  latencyMs: number | null = null;
  latencyWarn = false;
  qualityText = '\u2014';

  onLatency(latency_ms: number): void {
    this.latencyMs = latency_ms;
    this.latencyWarn = latency_ms > 700;
  }

  onAbr(to: string, throughput_kbps: number): void {
    this.qualityText = `${to} ${(throughput_kbps / 1000).toFixed(1)} Mbps`;
  }

  get latencyText(): string {
    return this.latencyMs !== null ? `${this.latencyMs} ms` : '\u2014 ms';
  }
}

// ─── Web Component ────────────────────────────────────────────────────────────

const _HTMLElementBase = (
  typeof HTMLElement !== 'undefined' ? HTMLElement : EventTarget
) as typeof HTMLElement;

export class MoQWatch extends _HTMLElementBase {
  private canvas: HTMLCanvasElement | null = null;
  private connection: any = null; // Watch.Net.Connection
  private player: any = null; // Watch.Player
  private frameCount: number = 0;
  private abr: AbrController | null = null; // Controlador ABR
  private abrTickInterval: number | null = null; // ID del setInterval para ABR tick
  private lastAbrTickTime: number = 0;
  private segmentBytesAccumulated: number = 0; // Acumular bytes entre ticks

  // Overlay management
  private _overlayEngine: OverlayEngine | null = null;
  private overlayIframe: HTMLIFrameElement | null = null;
  private overlayOrigin: string = '';
  private interactionSubscription: any = null; // Suscripción al track 'interaction'
  private overlaySync: OverlaySyncScheduler | null = null; // Scheduler de sync de overlays
  private currentPtsMs: number = 0; // PTS actual del vídeo (actualizado por sync track)
  private _logic = new PlayerLogic();
  private _hud = new HudState();

  constructor() {
    super();
    if (typeof (this as any).attachShadow === 'function') {
      this.attachShadow({ mode: 'open' });
    }
  }

  async connectedCallback(): Promise<void> {
    this.render();
    await this._logic.acquireToken();
    this.init();
  }

  disconnectedCallback() {
    this.cleanup();
  }

  private _fetchCertHash(): Promise<string | null> {
    return fetchCertHash(() => this.getAttribute('cert-hash'));
  }

  private render(): void {
    if (!this.shadowRoot) return;
    const isEmbed = this.getAttribute('embed') === '1';
    this.shadowRoot.innerHTML = buildShadowHtml(isEmbed);
    this.canvas = this.shadowRoot.querySelector('canvas');

    // Wire retry button
    const retryBtn = this.shadowRoot.querySelector('.status-retry') as HTMLButtonElement | null;
    retryBtn?.addEventListener('click', () => {
      this._logic.reconnectAttempt = 0;
      this._setState('connecting');
      this.init();
    });

    // HUD hover visibility (non-embed mode only)
    if (!isEmbed) {
      this.addEventListener('mouseenter', () => {
        const hud = this.shadowRoot?.querySelector('#hud');
        if (hud) { hud.classList.remove('hud-hidden'); hud.classList.add('hud-visible'); }
      });
      this.addEventListener('mouseleave', () => {
        const hud = this.shadowRoot?.querySelector('#hud');
        if (!hud) return;
        setTimeout(() => {
          hud.classList.remove('hud-visible');
          hud.classList.add('hud-hidden');
        }, 3000);
      });
    }

    // Update HUD on telemetry events (dispatched on self)
    this.addEventListener('moq:latency', (e: Event) => {
      const { latency_ms } = (e as CustomEvent).detail;
      this._hud.onLatency(latency_ms);
      this._updateHud();
      if (!isEmbed) {
        const hud = this.shadowRoot?.querySelector('#hud');
        if (hud) { hud.classList.remove('hud-hidden'); hud.classList.add('hud-visible'); }
      }
    });

    this.addEventListener('moq:abr', (e: Event) => {
      const { to, throughput_kbps } = (e as CustomEvent).detail;
      this._hud.onAbr(to, throughput_kbps);
      this._updateHud();
    });
  }

  private async init() {
    try {
      // Cargar dinámicamente @moq/watch y @moq/signals
      const Watch = await import('@moq/watch');
      const Signals = await import('@moq/signals');

      const url = this.getAttribute('url') || 'https://127.0.0.1:4443/anon';
      const name = this.getAttribute('name') || 'anon/live1';
      const certHash = await this._fetchCertHash();
      const abrWindow = parseInt(this.getAttribute('abr-window') || '5', 10);

      if (!this.canvas) {
        throw new Error('Canvas element not found in shadow DOM');
      }

      // Configurar Watch.Net.Connection con serverCertificateHashes si cert-hash está presente
      const connectionConfig: any = {
        url: new URL(url),
        enabled: true,
        webtransport: {
          serverCertificateHashes: certHash
            ? [
                {
                  algorithm: 'sha-256',
                  value: certHash, // Hex string del SHA-256
                },
              ]
            : [],
        },
        websocket: { enabled: false },
      };

      // Crear conexión
      this.connection = new Watch.Net.Connection(connectionConfig);

      // Crear player headless (sin custom element, solo API)
      this.player = new Watch.Player({
        origin: this.connection.origin,
        probe: this.connection.probe,
        name: Watch.Net.Path.from(name),
        canvas: this.canvas,
        muted: new Signals.Signal(true),
        delay: 'auto',
        visible: 'always',
      });

      // Instanciar controlador ABR
      this.abr = new AbrController(DEFAULT_RENDITIONS[1], {
        window: abrWindow,
        hysteresisUp: 3000,
        hysteresisDown: 1000,
      });

      // Iniciar tick ABR cada 2 segundos (aproximadamente con IDR frames)
      this.lastAbrTickTime = Date.now();
      this.segmentBytesAccumulated = 0;
      this.abrTickInterval = window.setInterval(() => {
        this.tickAbr();
      }, 2000);

      // Inicializar overlay sandbox
      await this.initializeOverlay();

      // Instanciar OverlayEngine sobre el contenedor de overlays
      const overlayRoot = this.shadowRoot?.querySelector('#overlay-container') as HTMLElement | null;
      if (overlayRoot) {
        this._overlayEngine = new OverlayEngine(overlayRoot);
      }

      // Inicializar scheduler de sync para overlays e interacciones
      this.overlaySync = new OverlaySyncScheduler(() => this.currentPtsMs, {
        maxDeviationMs: 100,
        jitterWindowSize: 5,
        onMetrics: (deviation: TimingDeviation) => {
          // Emitir métrica de desviación para telemetría
          this.dispatchEvent(
            new CustomEvent('moq:overlay-sync', {
              detail: { deviation },
              bubbles: true,
            })
          );
        },
      });

      // Suscribirse al track 'interaction' para eventos sincronizados con vídeo
      this.subscribeToInteractionTrack();

      // Emitir evento de ready
      this.dispatchEvent(
        new CustomEvent('moq:ready', {
          detail: { url, name, frameCount: this.frameCount },
          bubbles: true,
        })
      );

      this._setState('live');
      this._logic.handleReady();
      this.frameCount++;
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      console.error('[MoQWatch] Error:', message);
      this.dispatchEvent(
        new CustomEvent('moq:error', {
          detail: { message },
          bubbles: true,
        })
      );
      this._scheduleReconnect();
    }
  }

  /**
   * Inicializa el iframe sandbox para el overlay
   * - sandbox="allow-scripts" sin allow-same-origin (aislamiento de DOM)
   * - carga HTML via srcdoc (autocontenido)
   * - comunicación via postMessage
   */
  private async initializeOverlay() {
    try {
      const container = this.shadowRoot?.querySelector('#overlay-container');
      if (!container) return;

      // Crear iframe con sandbox
      this.overlayIframe = document.createElement('iframe');
      this.overlayIframe.setAttribute('sandbox', 'allow-scripts');
      this.overlayIframe.setAttribute('title', 'Overlay interactions');

      // Cargar poll.html vía srcdoc (autocontenido)
      const overlayHtml = await this.fetchOverlayHtml();
      this.overlayIframe.srcdoc = overlayHtml;

      container.appendChild(this.overlayIframe);

      // Registrar listener para mensajes del overlay
      window.addEventListener('message', (event) => this.handleOverlayMessage(event));

      // Establecer el origen esperado para validación de seguridad
      this.overlayOrigin = window.location.origin;

      console.debug('[MoQWatch] Overlay sandbox initialized');
    } catch (error) {
      console.warn('[MoQWatch] Could not initialize overlay:', error);
      // No fallar si overlay no está disponible; continuar sin él
    }
  }

  /**
   * Fetch el HTML del overlay (poll.html)
   * En desarrollo, este archivo está en overlays/poll.html
   */
  private async fetchOverlayHtml(): Promise<string> {
    try {
      const response = await fetch('/overlays/poll.html');
      if (!response.ok) {
        throw new Error(`Failed to fetch poll.html: ${response.status}`);
      }
      return await response.text();
    } catch (error) {
      console.warn('[MoQWatch] Could not fetch poll.html, using minimal overlay:', error);
      // Fallback: overlay vacío
      return `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="UTF-8">
          <style>
            body { margin: 0; padding: 0; font-family: sans-serif; }
            #placeholder { display: none; }
          </style>
        </head>
        <body>
          <div id="placeholder"></div>
          <script>
            window.addEventListener('message', (event) => {
              console.debug('[Overlay] Message received:', event.data);
            });
          </script>
        </body>
        </html>
      `;
    }
  }

  /**
   * Maneja mensajes postMessage del overlay
   * - Valida origen para seguridad
   * - Procesa votos y envía al servidor
   */
  private handleOverlayMessage(event: MessageEvent) {
    // Aceptar mensajes del legacy iframe O de cualquier iframe gestionado por el OverlayEngine
    const isLegacyOverlay = event.source === this.overlayIframe?.contentWindow;
    const isEngineOverlay = this._overlayEngine?.isKnownSource(event.source as WindowProxy) ?? false;
    if (!isLegacyOverlay && !isEngineOverlay) {
      return;
    }

    const message = event.data as OverlayMessage;
    if (!message || !message.type) return;

    console.debug('[MoQWatch] Overlay message:', message);

    if (message.type === 'interaction:vote') {
      this.submitVote(message.data);
    } else if (message.type === 'overlay:action') {
      // Re-emitir como evento del componente para que el host pueda reaccionar
      this.dispatchEvent(new CustomEvent('moq:overlay-action', { detail: message.payload, bubbles: true }));
      // Si la acción es un voto, procesarlo también
      if (message.payload?.kind === 'vote') {
        this.submitVote(message.payload);
      }
    }
  }

  /**
   * Envía un voto del usuario al servidor vía POST /interactions.
   * Usa Bearer token del viewer si está disponible; si no, intenta sin auth.
   */
  private async submitVote(voteData: unknown): Promise<void> {
    try {
      const broadcast = this.getAttribute('name') || 'anon/live1';
      const headers: Record<string, string> = { 'Content-Type': 'application/json' };
      if (this._logic.viewerToken) {
        headers['Authorization'] = `Bearer ${this._logic.viewerToken}`;
      }
      const payload: Record<string, unknown> = { broadcast, kind: 'vote', payload: voteData };
      const sessionToken = this.getAttribute('session-token');
      if (sessionToken) payload['session_token'] = sessionToken;
      const clientId = this.getAttribute('client-id');
      if (clientId) payload['client_id'] = clientId;
      const response = await fetch('/interactions', {
        method: 'POST',
        headers,
        body: JSON.stringify(payload),
      });
      if (!response.ok) throw new Error(`Vote submission failed: ${response.status}`);
      console.info('[MoQWatch] Vote submitted:', await response.json());
    } catch (error) {
      console.error('[MoQWatch] Error submitting vote:', error);
    }
  }

  /**
   * Suscribirse al track 'interaction' del broadcast
   * Recibe InteractionEvent y los despacha al overlay
   */
  private subscribeToInteractionTrack() {
    if (!this.connection || !this.player) {
      console.warn('[MoQWatch] Connection or player not ready for interaction subscription');
      return;
    }

    try {
      // TODO: Implementar suscripción al track 'interaction' via Watch.Net.Connection
      // Esta API depende de cómo esté implementada la suscripción a tracks en @moq/watch v0.6.1
      // Por ahora, placeholder que muestra la estructura esperada

      console.debug('[MoQWatch] Interaction track subscription initialized (placeholder)');

      // Ejemplo de cómo se vería cuando esté disponible:
      // this.interactionSubscription = this.connection.subscribe({
      //   namespace: this.player.name,
      //   trackName: 'interaction',
      // });
      //
      // this.interactionSubscription.onObject = (object: any) => {
      //   try {
      //     const payload = JSON.parse(object.payload);
      //     this.dispatchInteractionEvent(payload as InteractionEvent);
      //   } catch (error) {
      //     console.error('Failed to parse interaction event:', error);
      //   }
      // };
    } catch (error) {
      console.warn('[MoQWatch] Could not subscribe to interaction track:', error);
    }
  }

  /**
   * Despacha un InteractionEvent al overlay vía postMessage
   * Sincronizado con PTS del vídeo mediante OverlaySyncScheduler
   */
  private dispatchInteractionEvent(event: InteractionEvent) {
    if (!this.overlayIframe || !this.overlayIframe.contentWindow) {
      console.warn('[MoQWatch] Overlay iframe not ready');
      return;
    }

    if (!this.overlaySync) {
      console.warn('[MoQWatch] OverlaySync scheduler not initialized');
      return;
    }

    // Extraer PTS del timestamp del evento (en milisegundos)
    let ptsMsTarget = 0;
    if (event.timestamp && typeof event.timestamp === 'object') {
      if ('pts_90khz' in event.timestamp && event.timestamp.pts_90khz) {
        // Convertir de 90kHz a milisegundos: pts_ms = pts_90khz / 90
        ptsMsTarget = event.timestamp.pts_90khz / 90;
      } else if ('wallclock_ns' in event.timestamp && event.timestamp.wallclock_ns) {
        // Convertir de nanosegundos a milisegundos
        ptsMsTarget = event.timestamp.wallclock_ns / 1e6;
      }
    }

    if (ptsMsTarget <= 0) {
      console.warn('[MoQWatch] InteractionEvent without valid PTS, dispatching immediately');
      // Fallback: despachar inmediatamente sin scheduler
      const message: OverlayMessage = {
        type: `interaction:${event.kind}`,
        data: event,
      };
      this.overlayIframe.contentWindow.postMessage(message, this.overlayOrigin);
      return;
    }

    // Schedule la ejecución sincronizada con el PTS
    this.overlaySync.schedule(
      event.id,
      ptsMsTarget,
      () => {
        const message: OverlayMessage = {
          type: `interaction:${event.kind}`,
          data: event,
        };

        try {
          if (this.overlayIframe && this.overlayIframe.contentWindow) {
            this.overlayIframe.contentWindow.postMessage(message, this.overlayOrigin);
            console.debug('[MoQWatch] Interaction event dispatched to overlay:', event);
          }
        } catch (error) {
          console.error('[MoQWatch] Error posting message to overlay:', error);
        }
      },
      'interaction'
    );
  }

  /**
   * Despacha un OverlayPayload al overlay vía postMessage
   * Sincronizado con PTS del vídeo mediante OverlaySyncScheduler
   */
  private dispatchOverlayPayload(payload: any) {
    if (!this.overlayIframe || !this.overlayIframe.contentWindow) {
      console.warn('[MoQWatch] Overlay iframe not ready');
      return;
    }

    if (!this.overlaySync) {
      console.warn('[MoQWatch] OverlaySync scheduler not initialized');
      return;
    }

    // Extraer PTS del timestamp del payload (en milisegundos)
    let ptsMsTarget = 0;
    if (payload.timestamp && typeof payload.timestamp === 'object') {
      if ('pts_90khz' in payload.timestamp && payload.timestamp.pts_90khz) {
        // Convertir de 90kHz a milisegundos
        ptsMsTarget = payload.timestamp.pts_90khz / 90;
      } else if ('wallclock_ns' in payload.timestamp && payload.timestamp.wallclock_ns) {
        // Convertir de nanosegundos a milisegundos
        ptsMsTarget = payload.timestamp.wallclock_ns / 1e6;
      }
    }

    if (ptsMsTarget <= 0) {
      console.warn('[MoQWatch] OverlayPayload without valid PTS, dispatching immediately');
      // Fallback: despachar inmediatamente sin scheduler
      const message: OverlayMessage = {
        type: 'overlay:render',
        data: payload,
      };
      this.overlayIframe.contentWindow.postMessage(message, this.overlayOrigin);
      return;
    }

    // Schedule la ejecución sincronizada con el PTS
    this.overlaySync.schedule(
      payload.id,
      ptsMsTarget,
      () => {
        const message: OverlayMessage = {
          type: 'overlay:render',
          data: payload,
        };

        try {
          if (this.overlayIframe && this.overlayIframe.contentWindow) {
            this.overlayIframe.contentWindow.postMessage(message, this.overlayOrigin);
            console.debug('[MoQWatch] Overlay payload dispatched to overlay:', payload);
          }
        } catch (error) {
          console.error('[MoQWatch] Error posting message to overlay:', error);
        }
      },
      'overlay'
    );
  }

  private cleanup() {
    try {
      this._overlayEngine?.clearAll();
      this._overlayEngine = null;
      this._logic.cleanup();
      if (this.abrTickInterval !== null) {
        clearInterval(this.abrTickInterval);
        this.abrTickInterval = null;
      }
      if (this.overlayIframe) {
        this.overlayIframe.remove();
        this.overlayIframe = null;
      }
      if (this.interactionSubscription) {
        this.interactionSubscription.close();
        this.interactionSubscription = null;
      }
      if (this.overlaySync) {
        this.overlaySync.cleanup();
        this.overlaySync = null;
      }
      if (this.player) {
        this.player.close();
        this.player = null;
      }
      if (this.connection) {
        this.connection.close();
        this.connection = null;
      }
    } catch (error) {
      console.error('[MoQWatch] Error during cleanup:', error);
    }
  }

  /**
   * Tick del controlador ABR (cada ~2 segundos)
   * Procesa muestras de throughput y decide si cambiar rendition
   */
  private tickAbr() {
    if (!this.abr) return;

    const now = Date.now();
    const durationMs = now - this.lastAbrTickTime;

    // Añadir muestra de throughput (usar bytes acumulados en este período)
    // En un escenario real, estos bytes vendrían de eventos de decodificación
    // Por ahora usamos una estimación basada en la rendition actual
    const estimatedBytes = this.estimateBytesPerTick();
    this.abr.addSample(estimatedBytes, durationMs);

    // Obtener sugerencia y emitir evento si hay cambio
    const suggestion = this.abr.getSuggestion(DEFAULT_RENDITIONS);
    if (suggestion) {
      const fromName = this.abr.getState().currentRendition;
      const throughput = this.abr.getSmoothedThroughput();

      // TODO: Actualizar Watch.Player con la nueva rendition
      // Esto requiere API en Watch.Player que no está documentada en v0.6.1
      // Por ahora solo emitimos el evento para que la app pueda reaccionar

      this.dispatchEvent(
        new CustomEvent('moq:abr', {
          detail: {
            from: fromName,
            to: suggestion.name,
            throughput_kbps: throughput,
          },
          bubbles: true,
        })
      );

      console.info(
        `[ABR] Conmutación: ${fromName} → ${suggestion.name} (${throughput.toFixed(2)} kbps)`
      );
    }

    // Resetear acumulador
    this.lastAbrTickTime = now;
    this.segmentBytesAccumulated = 0;
  }

  private _setState(state: PlayerState): void {
    this._logic.state = state;
    const overlay = this.shadowRoot?.querySelector('#status-overlay') as HTMLElement | null;
    if (!overlay) return;
    overlay.classList.remove('status-connecting', 'status-live', 'status-error', 'status-unavailable');
    overlay.classList.add(`status-${state}`);
    const textEl = overlay.querySelector('.status-text') as HTMLElement | null;
    if (textEl) {
      const labels: Record<PlayerState, string> = {
        connecting: 'Conectando al relay…',
        live: '🔴 EN DIRECTO',
        error: 'Error de conexión. Reconectando…',
        unavailable: 'Stream no disponible',
      };
      textEl.textContent = labels[state];
    }
    if (state === 'live') {
      setTimeout(() => { (overlay as HTMLElement).style.display = 'none'; }, 3000);
    }
  }

  private _scheduleReconnect(): void {
    this._logic.handleError((delay) => {
      this._startCountdown(delay);
      return setTimeout(() => this.init(), delay);
    });
    this._setState(this._logic.state); // sync DOM to what handleError set
  }

  private _startCountdown(delayMs: number): void {
    const overlay = this.shadowRoot?.querySelector('#status-overlay');
    const textEl = overlay?.querySelector('.status-text') as HTMLElement | null;
    if (!textEl) return;
    let remaining = Math.ceil(delayMs / 1000);
    textEl.textContent = `Reconectando en ${remaining}s…`;
    const iv = setInterval(() => {
      remaining--;
      if (remaining > 0) {
        textEl.textContent = `Reconectando en ${remaining}s…`;
      } else {
        clearInterval(iv);
        textEl.textContent = 'Reconectando…';
      }
    }, 1000);
  }

  private _updateHud(): void {
    const hud = this.shadowRoot?.querySelector('#hud');
    if (!hud) return;
    const latencyEl = hud.querySelector('#hud-latency') as HTMLElement | null;
    if (latencyEl) {
      latencyEl.textContent = this._hud.latencyText;
      if (this._hud.latencyWarn) {
        latencyEl.classList.add('hud-latency-warn');
      } else {
        latencyEl.classList.remove('hud-latency-warn');
      }
    }
    const qualityEl = hud.querySelector('#hud-quality') as HTMLElement | null;
    if (qualityEl) qualityEl.textContent = this._hud.qualityText;
  }

  /**
   * Estima bytes decodificados por tick ABR
   * En un escenario real, estos datos vendrían de eventos del decoder
   */
  private estimateBytesPerTick(): number {
    // Estimación: 2 segundos × bitrate actual en bytes/s
    const currentState = this.abr?.getState();
    if (!currentState) return 0;

    const rendition = DEFAULT_RENDITIONS.find(
      (r) => r.name === currentState.currentRendition
    );
    if (!rendition) return 0;

    // bitrate_kbps → bytes en 2 segundos
    // kbps = kilobits per second
    // bytes = (kbps * 1000) / 8 * 2 segundos
    return (rendition.bitrate_kbps * 1000) / 8 * 2;
  }
}

if (typeof customElements !== 'undefined') {
  customElements.define('moq-watch', MoQWatch);
}
