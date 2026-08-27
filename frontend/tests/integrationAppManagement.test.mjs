import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  INVOICE_API_ENDPOINT,
  buildServerEnvSnippet,
  canRotateIntegrationApp,
  createOneTimeSecretState,
  filterIntegrationApps,
  getIntegrationAppStatus,
} from '../src/views/system/integrationAppManagement.js'


test('uses the production invoice endpoint and builds a server-only environment snippet', () => {
  assert.equal(INVOICE_API_ENDPOINT, 'https://leshine.work/api/integrations/v1')

  const snippet = buildServerEnvSnippet('ark_live_secret')
  assert.match(snippet, /ARK_INVOICE_API_BASE_URL=https:\/\/leshine\.work\/api\/integrations\/v1/)
  assert.match(snippet, /ARK_INVOICE_API_TOKEN=ark_live_secret/)
  assert.doesNotMatch(snippet, /localStorage|sessionStorage|window\.|document\./)
})


test('filters apps by name, owner, suffix and lifecycle status', () => {
  const rows = [
    {
      name: 'Sales portal', owner_username: 'li', owner_real_name: 'Li Ming',
      token_suffix: 'ABC123', is_active: true, expires_at: null,
    },
    {
      name: 'Expired site', owner_username: 'wang', owner_real_name: 'Wang',
      token_suffix: 'OLD456', is_active: true, expires_at: '2026-08-25T10:00:00',
    },
    {
      name: 'Revoked site', owner_username: 'zhou', owner_real_name: 'Zhou',
      token_suffix: 'OFF789', is_active: false, expires_at: null,
    },
  ]
  const now = new Date('2026-08-26T00:00:00+08:00')

  assert.deepEqual(filterIntegrationApps(rows, { keyword: 'abc123', status: 'active' }, now), [rows[0]])
  assert.deepEqual(filterIntegrationApps(rows, { keyword: 'wang', status: 'expired' }, now), [rows[1]])
  assert.deepEqual(filterIntegrationApps(rows, { keyword: '', status: 'revoked' }, now), [rows[2]])
})


test('status labels distinguish active, expired and revoked apps', () => {
  const now = new Date('2026-08-26T00:00:00+08:00')
  assert.deepEqual(getIntegrationAppStatus({ is_active: true, expires_at: null }, now), {
    key: 'active', label: '有效', type: 'success',
  })
  assert.deepEqual(getIntegrationAppStatus({ is_active: true, expires_at: '2026-08-25T23:59:59' }, now), {
    key: 'expired', label: '已过期', type: 'warning',
  })
  assert.deepEqual(getIntegrationAppStatus({ is_active: false }, now), {
    key: 'revoked', label: '已吊销', type: 'info',
  })
})


test('only an active, unexpired app offers credential rotation', () => {
  const now = new Date('2026-08-26T00:00:00+08:00')
  assert.equal(canRotateIntegrationApp({ is_active: true, expires_at: null }, now), true)
  assert.equal(canRotateIntegrationApp({
    is_active: true,
    expires_at: '2026-08-25T23:59:59',
  }, now), false)
  assert.equal(canRotateIntegrationApp({ is_active: false, expires_at: null }, now), false)
})


test('one-time secret state clears plaintext on demand', () => {
  const state = createOneTimeSecretState()
  const issued = { id: 1, token: 'ark_live_once', name: 'Sales portal' }

  state.show(issued)
  assert.equal(state.current(), issued)
  state.clear()
  assert.equal(state.current(), null)
})


test('admin client and API functions use the integrations admin contract', () => {
  const clients = readFileSync(new URL('../src/api/clients.js', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../src/api/integrationApps.js', import.meta.url), 'utf8')

  assert.match(clients, /integrationClient\s*=\s*createApiClient\(\{\s*baseURL:\s*['"]\/api\/integrations\/admin['"]/)
  assert.match(api, /\.get\(['"]\/user-candidates['"]/)
  assert.match(api, /\.get\(['"]\/apps['"]/)
  assert.match(api, /\.post\(['"]\/apps['"]/)
  assert.match(api, /current_token_suffix/)
  assert.match(api, /\.delete\(`\/apps\/\$\{appId\}`\)/)
})


test('navigation is protected and lifecycle updates expiry while clearing secrets and timers', () => {
  const navigation = readFileSync(new URL('../src/config/navigation.js', import.meta.url), 'utf8')
  const page = readFileSync(new URL('../src/views/system/IntegrationAppManagement.vue', import.meta.url), 'utf8')

  assert.match(navigation, /path: ['"]\/system\/integration-apps['"]/)
  assert.match(navigation, /permission: ['"]integration:admin['"]/)
  assert.match(page, /@closed="clearIssuedSecret"/)
  assert.match(page, /currentNow/)
  assert.match(page, /setInterval\([\s\S]*60_000/)
  assert.match(page, /clearInterval/)
  assert.match(page, /onBeforeUnmount\(cleanupPage\)/)
  assert.match(page, /canRotateIntegrationApp\(row, currentNow\)/)
  assert.match(page, /已过期，请新建凭证/)
  assert.match(page, /服务端调用，禁止放浏览器/)
  assert.doesNotMatch(page, /localStorage|sessionStorage|console\.(?:log|info|warn|error)|window\.location|URLSearchParams/)
  assert.doesNotMatch(page, /prefers-reduced-motion/)
})
