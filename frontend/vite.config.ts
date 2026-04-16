import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../app/static/dist',
    emptyOutDir: true,
    manifest: true,
  },
  server: {
    port: 5173,
    proxy: {
      '^/(api|claims|login|logout|dashboard|venues|events)$': 'http://127.0.0.1:5000',
      '^/(api|claims|login|logout|dashboard|venues|events)/': 'http://127.0.0.1:5000',
    },
  },
})
