import { estimateNTPOffset, calculateLatency, formatLatency } from './latency';
import { AbrController, DEFAULT_RENDITIONS, type Rendition } from './abr';
import { OverlaySyncScheduler, type TimingDeviation } from './overlay-sync';

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

export class MoQWatch extends HTMLElement {
  private canvas: HTMLCanvasElement | null = null;
  private connection: any = null; // Watch.Net.Connection
  private player: any = null; // Watch.Player
  private frameCount: number = 0;
  private abr: AbrController | null = null; // Controlador ABR
  private abrTickInterval: number | null = null; // ID del setInterval para ABR tick
  private lastAbrTickTime: number = 0;
  private segmentBytesAccumulated: number = 0; // Acumular bytes entre ticks

  // Overlay management
  private overlayIframe: HTMLIFrameElement | null = null;
  private overlayOrigin: string = '';
  private interactionSubscription: any = null; // Suscripción al track 'interaction'
  private overlaySync: OverlaySyncScheduler | null = null; // Scheduler de sync de overlays
  private currentPtsMs: number = 0; // PTS actual del vídeo (actualizado por sync track)

  constructor() {
    super();
    this.attachShadow({ mode: 'open' });
  }

  connectedCallback() {
    this.render();
    this.init();
  }

  disconnectedCallback() {
    this.cleanup();
  }

  private render() {
    if (!this.shadowRoot) return;
    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          width: 100%;
          aspect-ratio: 16 / 9;
          background: #000;
          border-radius: 8px;
          overflow: hidden;
          position: relative;
        }
        canvas {
          width: 100%;
          height: 100%;
          display: block;
          object-fit: contain;
        }
        #overlay-container {
          position: absolute;
          top: 0;
          left: 0;
          width: 100%;
          height: 100%;
          pointer-events: none;
          z-index: 10;
        }
        #overlay-container iframe {
          width: 100%;
          height: 100%;
          border: none;
          pointer-events: auto;
        }
      </style>
      <canvas></canvas>
      <div id="overlay-container"></div>
    `;
    this.canvas = this.shadowRoot.querySelector('canvas');
  }

  private async init() {
    try {
      // Cargar dinámicamente @moq/watch y @moq/signals
      const Watch = await import('@moq/watch');
      const Signals = await import('@moq/signals');

      const url = this.getAttribute('url') || 'https://127.0.0.1:4443/anon';
      const name = this.getAttribute('name') || 'anon/live1';
      const certHash = this.getAttribute('cert-hash');
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
    // SEGURIDAD: Validar origen del mensaje
    if (event.origin !== this.overlayOrigin) {
      console.warn('[MoQWatch] Rejecting message from untrusted origin:', event.origin);
      return;
    }

    const message = event.data as OverlayMessage;
    if (!message || !message.type) return;

    console.debug('[MoQWatch] Overlay message:', message);

    if (message.type === 'interaction:vote') {
      // El overlay envía un voto; el player lo envía al servidor
      this.submitVote(message.data);
    }
  }

  /**
   * Envía un voto del usuario al servidor vía POST /interactions
   */
  private async submitVote(voteData: any) {
    try {
      const broadcast = this.getAttribute('name') || 'anon/live1';
      const sessionToken = this.getAttribute('session-token');

      if (!sessionToken) {
        console.warn('[MoQWatch] No session token; cannot submit vote');
        return;
      }

      const payload: any = {
        broadcast,
        session_token: sessionToken,
        kind: 'vote',
        payload: voteData,
      };

      // Incluir timestamp y client_id si están disponibles
      const clientId = this.getAttribute('client-id');
      if (clientId) {
        payload.client_id = clientId;
      }

      const response = await fetch('/interactions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });

      if (!response.ok) {
        throw new Error(`Vote submission failed: ${response.status}`);
      }

      const result = await response.json();
      console.info('[MoQWatch] Vote submitted successfully:', result);
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

// Registrar el custom element para que pueda usarse en HTML
customElements.define('moq-watch', MoQWatch);
