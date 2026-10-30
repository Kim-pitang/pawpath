import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(process.env.PAWPATH_WEB_PORT ?? 5173),
    proxy: {
      '/api': process.env.PAWPATH_API_TARGET ?? 'http://127.0.0.1:8000',
    },
  },
});
