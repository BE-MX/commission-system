import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'path'
export default defineConfig({ plugins: [vue()], resolve: { alias: { '@': path.resolve('src') } }, server: { host: '127.0.0.1', port: 8766, strictPort: true, proxy: { '/api': 'http://127.0.0.1:8767' } } })
