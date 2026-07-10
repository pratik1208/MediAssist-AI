import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// In dev, /api/* is proxied to the Django server so the browser only ever
// talks to one origin — no CORS setup needed on the backend.
const backendUrl = process.env.BACKEND_URL ?? 'http://localhost:8001'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': {
        target: backendUrl,
        changeOrigin: true,
      },
    },
  },
})
