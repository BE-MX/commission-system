import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: { host: '127.0.0.1', port: 3210, strictPort: true },
  // Production must serve /api/portal/v1 from the same trusted reverse proxy.
  // No implicit development connection to an existing Ark database or service.
  build: { sourcemap: false },
})
