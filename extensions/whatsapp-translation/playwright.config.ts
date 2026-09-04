import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/browser',
  testMatch: '**/*.spec.ts',
  fullyParallel: false,
  workers: 1,
  timeout: 20_000,
  expect: { timeout: 3_000 },
  reporter: 'list',
  outputDir: '../../tmp/whatsapp-composer-browser',
  use: {
    browserName: 'chromium',
    headless: true,
    viewport: { width: 1100, height: 800 },
    trace: 'off',
    screenshot: 'off',
    video: 'off',
  },
})
