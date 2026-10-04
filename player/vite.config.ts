import { defineConfig, type Plugin } from 'vite';
import fs from 'fs';
import path from 'path';
import type { IncomingMessage, ServerResponse } from 'http';

interface LatencyMetrics {
  samples: number;
  p50_ms: number | null;
  p95_ms: number | null;
  last_ms: number | null;
  timestamp: string;
}

/** Dev-only plugin: serves GET /metrics/latency and accepts POST updates from the player. */
function metricsLatencyPlugin(): Plugin {
  let latest: LatencyMetrics | null = null;

  return {
    name: 'metrics-latency',
    apply: 'serve',
    configureServer(server) {
      server.middlewares.use(
        '/metrics/latency',
        (req: IncomingMessage, res: ServerResponse, next: () => void) => {
          if (req.method === 'GET') {
            const payload: LatencyMetrics = latest ?? {
              samples: 0, p50_ms: null, p95_ms: null, last_ms: null,
              timestamp: new Date().toISOString(),
            };
            res.setHeader('Content-Type', 'application/json');
            res.setHeader('Cache-Control', 'no-store');
            res.end(JSON.stringify(payload));
          } else if (req.method === 'POST') {
            let body = '';
            req.on('data', (chunk: Buffer) => { body += chunk.toString(); });
            req.on('end', () => {
              try { latest = JSON.parse(body) as LatencyMetrics; } catch { /* malformed */ }
              res.statusCode = 204;
              res.end();
            });
          } else {
            next();
          }
        },
      );
    },
  };
}

// Cuando VITE_HTTPS=1, sirve con cert dedicado del player (player.key/player.pem, propiedad del usuario)
// El relay usa su propio cert; el hash del relay se pasa al player via URL (?cert=)
const CERT_DIR = path.resolve(__dirname, '../config/relay/certs');
const httpsConfig = process.env.VITE_HTTPS === '1' && fs.existsSync(`${CERT_DIR}/player.pem`)
  ? { key: fs.readFileSync(`${CERT_DIR}/player.key`), cert: fs.readFileSync(`${CERT_DIR}/player.pem`) }
  : undefined;

export default defineConfig({
  plugins: [metricsLatencyPlugin()],
  server: {
    host: true,
    port: process.env.VITE_HTTPS === '1' ? 5443 : 5173,
    strictPort: false,
    https: httpsConfig,
    headers: {
      // COEP/COOP necesarios para SharedArrayBuffer — desactivados cuando se sirve detrás de proxy (Tailscale)
      ...(process.env.VITE_PROXY ? {} : {
        'Cross-Origin-Opener-Policy': 'same-origin',
        'Cross-Origin-Embedder-Policy': 'require-corp',
      }),
    },
  },
  build: {
    target: 'ES2020',
    outDir: 'dist',
    rollupOptions: {
      input: 'index.html',
    },
  },
  define: {
    'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'development'),
  },
});
