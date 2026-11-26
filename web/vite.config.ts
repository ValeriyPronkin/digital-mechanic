import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// In development the API runs separately (make api-dev); the built app is served by FastAPI itself.
export default defineConfig({
  // Served by our FastAPI under /v2 (issue #52); the API of this UI is under /api/v2.
  base: '/v2/',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': process.env.API_URL ?? 'http://127.0.0.1:8080',
      '/health': process.env.API_URL ?? 'http://127.0.0.1:8080',
    },
  },
})
