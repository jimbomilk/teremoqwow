import { MoQClient } from '@kixelated/moq';
import { estimateNTPOffset, calculateLatency, formatLatency } from './latency';

/**
 * Catalog shape validation
 */
interface CatalogTrack {
  name: string;
  kind: 'video' | 'audio' | 'data' | 'sync';
  codec: string;
  init_track: string;
  bitrate_kbps?: number;
  width?: number;
  height?: number;
  framerate?: number;
  channels?: number;
  sample_rate_hz?: number;
  language?: string;
  role?: string;
  selection_group?: string;
}

interface Catalog {
  version: number;
  namespace: string;
  created_at?: {
    wallclock_ns: number;
    source: string;
  };
  tracks: CatalogTrack[];
}

/**
 * moq-watch Web Component
 *
 * Attributes:
 *   - url: MoQ relay URL (e.g., "https://relay:4443")
 *   - namespace: MoQ namespace (e.g., "teremoqwow/dev/live1")
 *   - broadcast: Track name to play (e.g., "video-high")
 *
 * Events:
 *   - moq:latency: {latency_ms, pts_ms, render_ts_ms}
 *   - moq:error: {message}
 */
export class MoQWatch extends HTMLElement {
  private canvas: HTMLCanvasElement | null = null;
  private ctx: CanvasRenderingContext2D | null = null;
  private moq: MoQClient | null = null;
  private decoder: VideoDecoder | null = null;
  private ntpOffset: number = 0;
  private frameCount: number = 0;
  private selectedTrack: CatalogTrack | null = null;

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
        }
      </style>
      <canvas></canvas>
    `;
    this.canvas = this.shadowRoot.querySelector('canvas');
  }

  private async init() {
    try {
      const url = this.getAttribute('url');
      const namespace = this.getAttribute('namespace');
      const broadcast = this.getAttribute('broadcast');

      if (!url || !namespace || !broadcast) {
        throw new Error('Missing required attributes: url, namespace, broadcast');
      }

      // Initialize MoQ client
      this.moq = new MoQClient(url);
      await this.moq.connect();

      this.emit('moq:status', { status: 'connected' });

      // Subscribe to catalog
      const catalog = await this.fetchCatalog(namespace);
      this.validateCatalog(catalog);

      // Find the track to play
      this.selectedTrack = catalog.tracks.find(
        (t) => t.name === broadcast && t.kind === 'video'
      );

      if (!this.selectedTrack) {
        throw new Error(
          `Track "${broadcast}" not found or not a video track in catalog`
        );
      }

      // Initialize NTP offset if available
      if (catalog.created_at?.wallclock_ns) {
        this.ntpOffset = estimateNTPOffset(catalog.created_at.wallclock_ns);
      }

      // Initialize VideoDecoder
      await this.initDecoder(this.selectedTrack);

      // Subscribe to init track + main track
      await this.subscribeToTracks(namespace, this.selectedTrack);

      this.emit('moq:ready', { track: this.selectedTrack.name });
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.emitError(message);
    }
  }

  private async fetchCatalog(namespace: string): Promise<Catalog> {
    if (!this.moq) throw new Error('MoQ client not initialized');

    // Subscribe to the "catalog" object in the namespace
    // MoQ catalog is typically at {namespace}/catalog
    const catalogPath = `${namespace}/catalog`;

    // Read the catalog from the namespace
    // Using MoQ's subscription mechanism
    const subscription = await this.moq.subscribe(catalogPath, {
      start_object: 0,
    });

    // Collect all data from the catalog object
    let catalogData = '';
    for await (const data of subscription.reader) {
      if (typeof data === 'string') {
        catalogData += data;
      } else if (data instanceof Uint8Array) {
        catalogData += new TextDecoder().decode(data);
      }
    }

    return JSON.parse(catalogData) as Catalog;
  }

  private validateCatalog(catalog: unknown): asserts catalog is Catalog {
    const cat = catalog as Catalog;
    if (!cat.version || cat.version !== 1) {
      throw new Error('Invalid catalog version');
    }
    if (!cat.namespace || typeof cat.namespace !== 'string') {
      throw new Error('Missing catalog namespace');
    }
    if (!Array.isArray(cat.tracks) || cat.tracks.length === 0) {
      throw new Error('Invalid or empty catalog tracks');
    }
  }

  private async initDecoder(track: CatalogTrack) {
    if (!this.canvas) {
      throw new Error('Canvas not initialized');
    }

    // Check if VideoDecoder is available
    if (!('VideoDecoder' in window)) {
      throw new Error('WebCodecs VideoDecoder not supported in this browser');
    }

    const config: VideoDecoderConfig = {
      codec: track.codec,
      width: track.width || 1920,
      height: track.height || 1080,
      optimizeForLatency: true,
    };

    // Verify codec support
    const support = await VideoDecoder.isConfigSupported(config);
    if (!support.supported) {
      throw new Error(
        `Codec ${track.codec} not supported. Supported configs: ${JSON.stringify(support.supported)}`
      );
    }

    this.decoder = new VideoDecoder({
      output: (frame: VideoFrame) => {
        this.renderFrame(frame, track);
      },
      error: (error: DOMException) => {
        this.emitError(`Decoder error: ${error.message}`);
      },
    });

    this.decoder.configure(config);
  }

  private async subscribeToTracks(namespace: string, track: CatalogTrack) {
    if (!this.moq) throw new Error('MoQ client not initialized');

    // Subscribe to init track first to get codec parameters
    const initTrackPath = `${namespace}/${track.init_track}`;
    const initSubscription = await this.moq.subscribe(initTrackPath, {
      start_object: 0,
    });

    for await (const data of initSubscription.reader) {
      if (this.decoder) {
        // Enqueue init segment to decoder
        const chunk = new EncodedVideoChunk({
          type: 'key',
          timestamp: 0,
          data: data instanceof Uint8Array ? data : new TextEncoder().encode(String(data)),
        });
        this.decoder.decode(chunk);
      }
    }

    // Subscribe to main video track
    const videoTrackPath = `${namespace}/${track.name}`;
    const videoSubscription = await this.moq.subscribe(videoTrackPath, {
      start_object: 0,
    });

    // Decode video chunks as they arrive
    for await (const chunk of videoSubscription.reader) {
      if (this.decoder) {
        try {
          const buffer =
            chunk instanceof Uint8Array ? chunk : new TextEncoder().encode(String(chunk));

          // Try to extract timestamp from chunk (MoQ provides in metadata)
          // For now, use current time as approximation
          const timestamp = performance.now() * 1000; // Convert to microseconds

          const encodedChunk = new EncodedVideoChunk({
            type: 'delta',
            timestamp,
            data: buffer,
          });
          this.decoder.decode(encodedChunk);
        } catch (err) {
          this.emitError(`Failed to decode chunk: ${err}`);
        }
      }
    }
  }

  private renderFrame(frame: VideoFrame, track: CatalogTrack) {
    if (!this.canvas || !this.ctx) {
      this.ctx = this.canvas?.getContext('2d');
      if (!this.ctx) {
        this.emitError('Failed to get canvas context');
        return;
      }
    }

    // Resize canvas to match frame dimensions if needed
    if (this.canvas.width !== frame.codedWidth || this.canvas.height !== frame.codedHeight) {
      this.canvas.width = frame.codedWidth;
      this.canvas.height = frame.codedHeight;
    }

    // Draw frame on canvas
    this.ctx.drawImage(frame as any, 0, 0);
    frame.close();

    this.frameCount++;

    // Emit latency event
    if (frame.timestamp !== undefined) {
      const latencyMetrics = calculateLatency(frame.timestamp, this.ntpOffset);
      this.emit('moq:latency', latencyMetrics);
      this.updateStats(latencyMetrics, track);
    }
  }

  private updateStats(latencyMetrics: any, track: CatalogTrack) {
    const statusEl = document.getElementById('status');
    const latencyEl = document.getElementById('latency');
    const framesEl = document.getElementById('frames');
    const codecEl = document.getElementById('codec');

    if (statusEl) statusEl.textContent = 'Reproduciendo';
    if (latencyEl) latencyEl.textContent = formatLatency(latencyMetrics.latency_ms);
    if (framesEl) framesEl.textContent = String(this.frameCount);
    if (codecEl) codecEl.textContent = track.codec;
  }

  private cleanup() {
    if (this.decoder) {
      this.decoder.close();
      this.decoder = null;
    }
    if (this.moq) {
      this.moq.close();
      this.moq = null;
    }
  }

  private emit(eventName: string, detail: any) {
    this.dispatchEvent(new CustomEvent(eventName, { detail }));
  }

  private emitError(message: string) {
    this.emit('moq:error', { message });

    // Update UI
    const errorContainer = document.getElementById('error-container');
    if (errorContainer) {
      const errorEl = document.createElement('div');
      errorEl.className = 'error';
      errorEl.textContent = `⚠️ Error: ${message}`;
      errorContainer.appendChild(errorEl);
    }

    const statusEl = document.getElementById('status');
    if (statusEl) statusEl.textContent = 'Error';
  }
}

// Register custom element
customElements.define('moq-watch', MoQWatch);
