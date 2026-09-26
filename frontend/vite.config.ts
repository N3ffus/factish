import { defineConfig } from 'vite';

export default defineConfig({
  base: process.env.FACTISH_BASE_PATH || '/',
  server: { proxy: { '/api': 'http://127.0.0.1:8000', '/avatars': 'http://127.0.0.1:8000' } },
});
