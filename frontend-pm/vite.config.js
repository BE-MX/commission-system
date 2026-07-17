import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// PM Hub 独立前端：与方舟主站无视觉血缘、无代码共享。
// dev 代理 /api → 本地后端（默认 8001，可用 PM_API_TARGET 覆盖）。
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 3100,
    proxy: {
      '/api': {
        target: process.env.PM_API_TARGET || 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
  build: {
    chunkSizeWarningLimit: 900,
  },
})
