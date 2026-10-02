import * as Moq from '@moq/net';
import { Signal } from '@moq/signals';
import * as Watch from '@moq/watch';
import { CircularBuffer, percentile, HISTORY_SIZE } from './metrics.js';

const _params = new URLSearchParams(location.search);
if (_params.get('embed') === '1') document.body.classList.add('embed');

const canvasEl = document.getElementById('moq-canvas') as HTMLCanvasElement;
const url = _params.get('relay')
  || canvasEl?.getAttribute('data-url')
  || import.meta.env.VITE_MOQ_RELAY_URL
  || 'https://127.0.0.1:4443/anon';
const name = _params.get('broadcast')
  || canvasEl?.getAttribute('data-name')
  || import.meta.env.VITE_RELAY_BROADCAST
  || 'anon/live1';
const certHash = _params.get('cert')
  || canvasEl?.getAttribute('data-cert-hash')
  || import.meta.env.VITE_MOQ_CERT_HASH
  || '';

const certHashDisplay = document.getElementById('cert-hash-display');
if (certHashDisplay) {
  certHashDisplay.textContent = certHash || '(no configurado, usando WebTransport sin validación)';
}

const container = document.createElement('div');
container.style.cssText = 'display:block;width:100%;aspect-ratio:16/9;background:#000;position:relative;overflow:hidden;border-radius:8px;cursor:pointer';

const canvas = document.createElement('canvas');
canvas.width = 1280;
canvas.height = 720;
canvas.style.cssText = 'width:100%;height:100%;display:block;object-fit:contain';
container.appendChild(canvas);

// Overlay 'click para activar audio' hasta el primer gesto del usuario
const audioOverlay = document.createElement('div');
audioOverlay.textContent = '🔊 Click para activar audio';
audioOverlay.style.cssText = 'position:absolute;bottom:12px;left:12px;background:rgba(0,0,0,0.75);color:#fff;padding:6px 12px;border-radius:4px;font-family:sans-serif;font-size:0.85rem;pointer-events:none;z-index:10';
container.appendChild(audioOverlay);

canvasEl?.replaceWith(container);

const connection = new Moq.Connection({
  url: new URL(url),
  enabled: true,
  webtransport: certHash
    ? { serverCertificateHashes: [{ algorithm: 'sha-256', value: certHash }] }
    : undefined,
  websocket: { enabled: false },
});

const muted = new Signal(true);
const volume = new Signal(0.7);

const player = new Watch.Player({
  origin: connection.origin,
  probe: connection.probe,
  name: Moq.Path.from(name),
  canvas: canvas,
  muted,
  volume,
  visible: 'always',
  // Buffer fijo de 500ms para absorber jitter en 1080p sin cortes de audio
  delay: 500 as any,
  buffer: 200 as any,
});

// Click en el video para desmutear (Chrome exige gesto del usuario)
container.addEventListener('click', () => {
  if (muted.peek()) {
    muted.set(false);
    audioOverlay.remove();
    console.log('[Player] audio activado');
  }
}, { once: false });

const statusEl = document.getElementById('status');
if (statusEl) statusEl.textContent = 'Conectando al relay...';

const applyTargetSize = () => {
  const dpr = window.devicePixelRatio || 1;
  const rect = container.getBoundingClientRect();
  if (rect.width > 0 && rect.height > 0) {
    const w = Math.round(rect.width * dpr);
    const h = Math.round(rect.height * dpr);
    (player.in.target as any).set?.({ width: w, height: h });
  }
};
applyTargetSize();
new ResizeObserver(applyTargetSize).observe(container);

// HUD stats
const latencyEl = document.getElementById('latency');
const framesEl  = document.getElementById('frames');
const codecEl   = document.getElementById('codec');

// Metrics accumulator — feeds /metrics/latency via Vite dev plugin
const _delayBuf = new CircularBuffer(HISTORY_SIZE);
let _sampleCount = 0;

declare global {
  interface Window {
    __moqMetrics: {
      samples: number;
      p50_ms: number | null;
      p95_ms: number | null;
      last_ms: number | null;
      timestamp: string;
    };
  }
}

// Contador de frames real via rAF: cuenta cada frame que el renderer pinta al canvas
let frameCount = 0;
let lastRenderedTs: number | undefined;
function frameLoop() {
  try {
    const rendererOut = (player as any).renderer?.out;
    const ts = rendererOut?.timestamp?.peek?.();
    if (typeof ts === 'number' && ts !== lastRenderedTs) {
      frameCount++;
      lastRenderedTs = ts;
    }
  } catch (_) {}
  requestAnimationFrame(frameLoop);
}
requestAnimationFrame(frameLoop);

// FPS medio de los últimos 2s
let lastFpsCheck = performance.now();
let lastFpsCount = 0;
let currentFps = 0;

setInterval(() => {
  try {
    const now = performance.now();
    const elapsed = (now - lastFpsCheck) / 1000;
    currentFps = (frameCount - lastFpsCount) / elapsed;
    lastFpsCheck = now;
    lastFpsCount = frameCount;

    // El catalog puede estar en distintas ubicaciones según versión de @moq/watch
    const broadcast = (player as any).broadcast;
    const catalog = broadcast?.catalog?.peek?.()
      ?? broadcast?.out?.catalog?.peek?.()
      ?? broadcast?.in?.catalog?.peek?.();

    // Estado: basado en si hay frames llegando (currentFps > 0) más que en el catalog
    if (statusEl) {
      if (currentFps > 1) {
        statusEl.textContent = muted.peek() ? '🔇 Reproduciendo' : '🔊 Reproduciendo';
      } else if (catalog) {
        statusEl.textContent = 'Suscrito · esperando frames...';
      } else {
        statusEl.textContent = 'Conectando al relay...';
      }
    }

    if (codecEl && catalog?.video?.renditions) {
      const rendition = Object.values(catalog.video.renditions)[0] as any;
      if (rendition?.codec) {
        codecEl.textContent = `${rendition.codec} @ ${rendition.codedWidth}x${rendition.codedHeight} · ${(rendition.bitrate/1e6).toFixed(1)} Mbps`;
      }
    }

    // Latencia glass-to-glass = delay del sync (jitter buffer real que aplica la librería)
    // sync.out.delay es la latencia efectiva calculada por MoQ (buffer + jitter estimado)
    const sync = (player as any).sync;
    const delay  = sync?.out?.delay?.peek?.();
    const jitter = sync?.out?.jitter?.peek?.();
    if (latencyEl && typeof delay === 'number') {
      const jitterStr = typeof jitter === 'number' ? ` ±${Math.round(jitter)}` : '';
      latencyEl.textContent = `${Math.round(delay)}${jitterStr} ms`;
    }

    // Accumulate into circular buffer and expose metrics
    if (typeof delay === 'number') {
      _delayBuf.push(delay);
      _sampleCount++;
      const sorted = _delayBuf.toArray().sort((a, b) => a - b);
      const metrics = {
        samples: _sampleCount,
        p50_ms: Math.round(percentile(sorted, 0.50)),
        p95_ms: Math.round(percentile(sorted, 0.95)),
        last_ms: Math.round(delay),
        timestamp: new Date().toISOString(),
      };
      window.__moqMetrics = metrics;
      // Push to Vite dev plugin (no-op in production since endpoint won't exist)
      fetch('/metrics/latency', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(metrics),
      }).catch(() => { /* dev-only endpoint, ignore errors in production */ });
    } else if (_sampleCount === 0) {
      window.__moqMetrics = {
        samples: 0, p50_ms: null, p95_ms: null, last_ms: null,
        timestamp: new Date().toISOString(),
      };
    }

    if (framesEl) framesEl.textContent = `${frameCount} · ${currentFps.toFixed(1)} fps`;
  } catch (_) {}
}, 1000);

console.log('[Player] Iniciado', { url, name, certHash: certHash.slice(0, 16) + '...' });
