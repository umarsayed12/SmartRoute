// Serve the frontend and proxy API traffic to the local SmartRoute backend.
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  plugins: [react()],
  build: { outDir: '../backend/static', emptyOutDir: true },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/v1': { target: process.env.SMARTROUTE_BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: true },
      '/health': { target: process.env.SMARTROUTE_BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: true },
      '/docs': { target: process.env.SMARTROUTE_BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: true },
      '/openapi.json': { target: process.env.SMARTROUTE_BACKEND_URL || 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
