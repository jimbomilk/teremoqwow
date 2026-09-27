import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: true,
    port: 5173,
    strictPort: false,
    headers: {
      'Cross-Origin-Opener-Policy': 'same-origin',
      'Cross-Origin-Embedder-Policy': 'require-corp',
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
