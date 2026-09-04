import { cpSync, mkdirSync, rmSync } from 'node:fs'
import { build } from 'vite'
import { aliases, buildTarget } from '../vite.config.ts'

rmSync('dist', { recursive: true, force: true })
mkdirSync('dist', { recursive: true })

await build({
  configFile: false,
  resolve: { alias: aliases },
  build: {
    target: buildTarget,
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        background: 'src/background/index.ts',
        popup: 'src/popup/index.html',
      },
      output: { entryFileNames: '[name].js' },
    },
  },
})

await build({
  configFile: false,
  resolve: { alias: aliases },
  build: {
    target: buildTarget,
    outDir: 'dist',
    emptyOutDir: false,
    rollupOptions: {
      input: 'src/content/index.ts',
      output: {
        format: 'iife',
        entryFileNames: 'content.js',
        inlineDynamicImports: true,
      },
    },
  },
})

cpSync('manifest.json', 'dist/manifest.json')
mkdirSync('dist/assets', { recursive: true })
for (const size of [16, 32, 48, 128]) {
  cpSync(`assets/icon-${size}.png`, `dist/assets/icon-${size}.png`)
}
