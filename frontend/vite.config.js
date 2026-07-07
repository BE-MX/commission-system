import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
import fs from 'fs'

export default defineConfig({
  plugins: [
    vue(),
    {
      name: 'mobile-page-serve',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          if (req.url === '/m' || req.url === '/m/') {
            const htmlPath = path.resolve(__dirname, 'public/m/index.html')
            const html = fs.readFileSync(htmlPath, 'utf-8')
            res.setHeader('Content-Type', 'text/html; charset=utf-8')
            res.end(html)
            return
          }
          next()
        })
      }
    }
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src')
    }
  },
  server: {
    port: 3000,
    proxy: {
      '/api': {
        target: 'http://localhost:8001',
        changeOrigin: true
      },
      '/uploads': {
        target: 'http://localhost:8001',
        changeOrigin: true
      }
    }
  },
  build: {
    rollupOptions: {
      output: {
        // 治理 F-7：稳定依赖拆独立 vendor chunk——业务代码变更不再打翻大依赖的浏览器缓存
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('echarts') || id.includes('zrender')) return 'vendor-echarts'
            if (id.includes('element-plus')) return 'vendor-element'
            return 'vendor'
          }
        }
      }
    }
  }
})
