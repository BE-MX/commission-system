import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../../..')
export default defineConfig({ root: frontend, envDir: false, plugins: [vue(), { name: 'deny-api', configureServer(server) { server.middlewares.use('/api', (_req, res) => { res.statusCode = 403; res.end('Blocked by isolated fixture') }) } }], resolve: { alias: { '@': path.join(frontend, 'src') } }, server: { host: '127.0.0.1', strictPort: true }, publicDir: false })
