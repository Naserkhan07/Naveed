import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// the browser never talks to localhost:8000 directly — vite proxies /api and /ws to the backend
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true, changeOrigin: true },
    },
  },
  preview: { host: '0.0.0.0', port: 5173, allowedHosts: true },
  build: { chunkSizeWarningLimit: 1500 },
});
