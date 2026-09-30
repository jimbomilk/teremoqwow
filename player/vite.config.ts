import { defineConfig } from 'vite';
import fs from 'fs';
import path from 'path';

// Cuando VITE_HTTPS=1, sirve con cert dedicado del player (player.key/player.pem, propiedad del usuario)
// El relay usa su propio cert; el hash del relay se pasa al player via URL (?cert=)
const CERT_DIR = path.resolve(__dirname, '../config/relay/certs');
const httpsConfig = process.env.VITE_HTTPS === '1' && fs.existsSync(`${CERT_DIR}/player.pem`)
  ? { key: fs.readFileSync(`${CERT_DIR}/player.key`), cert: fs.readFileSync(`${CERT_DIR}/player.pem`) }
  : undefined;

export default defineConfig({
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
    lib: {
      entry: 'src/main.ts',
      name: 'TeremoqwowPlayer',
      fileName: (format) => `player.${format === 'es' ? 'js' : 'umd.js'}`,
    },
    rollupOptions: {
      external: ['@moq/watch', '@moq/signals'],
      output: {
        globals: {
          '@moq/watch': 'MoQWatch',
          '@moq/signals': 'MoQSignals',
        },
      },
    },
  },
  define: {
    'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'development'),
  },
});
