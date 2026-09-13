/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url'

import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    allowedHosts: ["azurenergie.hasel.food"],
    host: true,
    port: 5173,
    proxy: {
      '/api': {
        // Set VITE_API_PROXY_TARGET=http://backend:8000 when running via
        // docker-compose, where the backend is a separate container rather
        // than reachable at localhost.
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
      // Uploaded files (e.g. treasury payment proofs) are served by Django
      // under MEDIA_URL - same backend, needs the same proxy so
      // root-relative document URLs from the API resolve in the browser.
      '/media': {
        target: process.env.VITE_API_PROXY_TARGET || 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test-setup.ts'],
  },
})
