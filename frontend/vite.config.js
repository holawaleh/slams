import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  plugins: [
    react(),
    // Installable app: manifest, icons and a service worker that keeps the
    // app shell (HTML, JS, CSS, icons) for offline start. API responses are
    // never cached - attendance must always be live.
    VitePWA({
      registerType: 'autoUpdate',
      injectRegister: false,          // registered in src/main.jsx
      includeAssets: ['favicon.svg', 'apple-touch-icon.png'],
      manifest: {
        id: '/',
        name: 'SLAMS - Smart Lecture Attendance',
        short_name: 'SLAMS',
        description: 'Lecture attendance by card tap: students, courses, timetable and reports.',
        lang: 'en',
        start_url: '/dashboard',
        scope: '/',
        display: 'standalone',
        display_override: ['standalone', 'minimal-ui'],
        orientation: 'any',
        background_color: '#1b1f2e',
        theme_color: '#1b1f2e',
        categories: ['education', 'productivity'],
        icons: [
          { src: 'pwa-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: 'pwa-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: 'maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        // Every app route opens from the cached shell when offline.
        navigateFallback: '/index.html',
        cleanupOutdatedCaches: true,
        // The API lives on another origin and is deliberately not cached.
        runtimeCaching: [],
      },
    }),
  ],
})
