import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Dev server runs on :5173 and proxies /api/* to the FastAPI backend on :8000,
// so the frontend can use relative URLs and never deals with CORS in dev.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
      // uploaded prescription images are served by FastAPI
      '/uploads': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
