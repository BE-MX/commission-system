import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import legacy from '@vitejs/plugin-legacy'
import path from 'path'
import fs from 'fs'

export default defineConfig({
  plugins: [
    vue(),
    legacy({
      // PDA 为 Android 6.0.1：同时输出 SystemJS 兼容包，避免老 Chrome 直接白屏。
      targets: ['Android >= 6', 'Chrome >= 49'],
    }),
    {
      // public/<dir>/ 静态页（/m/、/caigoujie/ 等）的目录 URL：Vite dev 不解析
      // 目录 index.html，会回退成 SPA 壳导致白屏。这里对齐生产 Nginx / 8001
      // 的行为——无斜杠先 301 补斜杠，再直出该目录的 index.html
      name: 'public-dir-index-serve',
      configureServer(server) {
        server.middlewares.use((req, res, next) => {
          const [urlPath, query] = req.url.split('?')
          if (urlPath === '/' || urlPath.includes('..')) return next()
          const dirPath = urlPath.endsWith('/') ? urlPath : urlPath + '/'
          const indexPath = path.resolve(__dirname, 'public', dirPath.slice(1), 'index.html')
          if (!fs.existsSync(indexPath)) return next()
          if (!urlPath.endsWith('/')) {
            res.statusCode = 301
            res.setHeader('Location', dirPath + (query ? '?' + query : ''))
            res.end()
            return
          }
          res.setHeader('Content-Type', 'text/html; charset=utf-8')
          res.end(fs.readFileSync(indexPath, 'utf-8'))
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
