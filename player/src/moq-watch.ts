import { estimateNTPOffset, calculateLatency, formatLatency } from './latency';
import { AbrController, DEFAULT_RENDITIONS, type Rendition } from './abr';

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
export class MoQWatch extends HTMLElement {
  private canvas: HTMLCanvasElement | null = null;
  private connection: any = null; // Watch.Net.Connection
  private player: any = null; // Watch.Player
  private frameCount: number = 0;
  private abr: AbrController | null = null; // Controlador ABR
  private abrTickInterval: number | null = null; // ID del setInterval para ABR tick
  private lastAbrTickTime: number = 0;
  private segmentBytesAccumulated: number = 0; // Acumular bytes entre ticks

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
        }
        canvas {
          width: 100%;
          height: 100%;
          display: block;
          object-fit: contain;
        }
      </style>
      <canvas></canvas>
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

  private cleanup() {
    try {
      if (this.abrTickInterval !== null) {
        clearInterval(this.abrTickInterval);
        this.abrTickInterval = null;
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
