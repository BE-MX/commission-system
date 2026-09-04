import { configDefaults, defineConfig } from 'vitest/config'
import { aliases, buildTarget } from './vite.config'

export default defineConfig({
  resolve: { alias: aliases },
  build: { target: buildTarget },
  test: { exclude: [...configDefaults.exclude, 'tests/browser/**'] },
})
