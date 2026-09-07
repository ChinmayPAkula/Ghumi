import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      // Frontend calls /api/... in dev. The backend ALSO expects the /api
      // prefix (see backend/app/main.py: include_router(prefix="/api")),
      // so this just forwards the path as-is to :8000 — no rewrite/strip.
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})