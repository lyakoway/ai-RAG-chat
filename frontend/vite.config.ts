import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The backend runs on :8000; proxy /api so the frontend can use same-origin URLs.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
