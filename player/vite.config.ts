import { defineConfig } from 'vite';

export default defineConfig({
  server: {
    host: true,
    port: 5173,
    strictPort: false,
  },
  build: {
    target: 'ES2020',
    lib: {
      entry: 'src/main.ts',
      name: 'TeremoqwowPlayer',
      fileName: (format) => `player.${format === 'es' ? 'js' : 'umd.js'}`,
    },
    rollupOptions: {
      external: ['@kixelated/moq'],
      output: {
        globals: {
          '@kixelated/moq': 'MoQ',
        },
      },
    },
  },
  define: {
    'process.env.NODE_ENV': JSON.stringify(process.env.NODE_ENV || 'development'),
  },
});
