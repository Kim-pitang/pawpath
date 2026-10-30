import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: Number(process.env.PAWPATH_WEB_PORT ?? 5173),
    // 휴대폰에서 실제 GPS를 쓰려면 HTTPS가 필요해 터널 주소를 허용한다.
    allowedHosts: ['.trycloudflare.com', '.ngrok-free.app'],
    proxy: {
      '/api': process.env.PAWPATH_API_TARGET ?? 'http://127.0.0.1:8000',
    },
  },
});
