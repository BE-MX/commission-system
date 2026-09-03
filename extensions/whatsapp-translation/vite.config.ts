import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

export const aliases = {
  '@': fileURLToPath(new URL('./src', import.meta.url)),
}

export const buildTarget = 'es2022'

export default defineConfig({
  resolve: { alias: aliases },
  build: { target: buildTarget },
})
