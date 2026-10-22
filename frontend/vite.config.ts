/// <reference types="vitest/config" />
import { readFileSync } from 'node:fs'
import { fileURLToPath, URL } from 'node:url'

import { defineConfig, type Plugin } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'

// One codebase, several customers that differ by name + logo only: the brand is
// picked at build time (VITE_BRAND, default `azur`), see brands/README.md.
const BRAND = process.env.VITE_BRAND || 'azur'
const brandDir = fileURLToPath(new URL(`./brands/${BRAND}/`, import.meta.url))
const brandInfo = JSON.parse(readFileSync(`${brandDir}brand.json`, 'utf-8'))

// Files the browser asks for at fixed URLs (tab icon, PWA icons, manifest) and
// the page title come from the brand folder instead of /public.
function brandPlugin(): Plugin {
  const manifest = JSON.stringify(
    {
      name: brandInfo.appName,
      short_name: brandInfo.name,
      start_url: '/',
      display: 'standalone',
      background_color: brandInfo.backgroundColor,
      theme_color: brandInfo.themeColor,
      icons: [
        { src: '/pwa-icon-192.png', sizes: '192x192', type: 'image/png' },
        { src: '/pwa-icon-512.png', sizes: '512x512', type: 'image/png' },
      ],
    },
    null,
    2,
  )
  const images = ['favicon.png', 'pwa-icon-192.png', 'pwa-icon-512.png']
  return {
    name: 'brand',
    transformIndexHtml: (html) => html.replaceAll('%BRAND_APP_NAME%', brandInfo.appName),
    configureServer(server) {
      server.middlewares.use((req, res, next) => {
        const path = (req.url || '').split('?')[0].slice(1)
        if (path === 'manifest.webmanifest') {
          res.setHeader('Content-Type', 'application/manifest+json')
          res.end(manifest)
        } else if (images.includes(path)) {
          res.setHeader('Content-Type', 'image/png')
          res.end(readFileSync(`${brandDir}${path}`))
        } else {
          next()
        }
      })
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'manifest.webmanifest', source: manifest })
      for (const name of images) {
        this.emitFile({ type: 'asset', fileName: name, source: readFileSync(`${brandDir}${name}`) })
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss(), brandPlugin()],
  resolve: {
    alias: {
      '@brand': brandDir,
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    allowedHosts: [".hasel.food"],
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
