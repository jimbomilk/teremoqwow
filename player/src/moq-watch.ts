import { estimateNTPOffset, calculateLatency, formatLatency } from './latency';

/**
 * moq-watch Web Component (Headless Player)
 *
 * Implementa la API real de @moq/watch@0.6.1 con Watch.Player + Watch.Net.Connection
 *
 * Attributes:
 *   - url: MoQ relay URL (default: "https://127.0.0.1:4443/anon")
 *   - name: Broadcast name (default: "anon/live1")
 *   - cert-hash: SHA-256 hex del cert del relay (opcional, para WebTransport self-signed)
 *
 * Events:
 *   - moq:ready: cuando el player está listo
 *   - moq:error: {message} cuando ocurre un error
 *   - moq:latency: {latency_ms, pts_ms, render_ts_ms, ntp_offset_ms}
 */
export class MoQWatch extends HTMLElement {
  private canvas: HTMLCanvasElement | null = null;
  private connection: any = null; // Watch.Net.Connection
  private player: any = null; // Watch.Player
  private frameCount: number = 0;

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
}

// Registrar el custom element para que pueda usarse en HTML
customElements.define('moq-watch', MoQWatch);
