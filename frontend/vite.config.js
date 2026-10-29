import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Dev: `npm run dev` proxies /api to the gateway published by docker compose (web container on :8080 also works).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { port: 5173, proxy: { '/api': 'http://localhost:8080' } },
})
