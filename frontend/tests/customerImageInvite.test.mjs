import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  INVITE_KEY,
  captureInviteToken,
  clearInviteToken,
  getInviteAuthorization,
  getInviteToken,
} from '../src/views/customer-image/inviteSession.js'

class MemoryStorage {
  #values = new Map()

  getItem(key) { return this.#values.get(key) ?? null }
  setItem(key, value) { this.#values.set(key, String(value)) }
  removeItem(key) { this.#values.delete(key) }
}

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function loadCreateApiClient({ accessToken = 'ark-token' } = {}) {
  const source = read('../src/api/request.js')
  const start = source.indexOf('export function createApiClient')
  const end = source.indexOf('const v1Client', start)
  const body = source.slice(start, end).replace('export function', 'function')
  const handlers = {}
  const axios = {
    create() {
      return {
        interceptors: {
          request: { use(handler) { handlers.request = handler } },
          response: {
            use(success, failure) {
              handlers.responseSuccess = success
              handlers.responseFailure = failure
            },
          },
        },
      }
    },
  }
  let cleared = 0
  const factory = new Function(
    'axios',
    'ElMessage',
    'useLoading',
    'getAccessToken',
    'clearAuthState',
    `${body}; return createApiClient`,
  )(
    axios,
    { error() {} },
    () => ({ show() {}, hide() {} }),
    () => accessToken,
    () => { cleared += 1 },
  )
  return { factory, handlers, cleared: () => cleared }
}

test('captureInviteToken stores a valid token and removes it from the visible URL', () => {
  const storage = new MemoryStorage()
  const calls = []
  const history = {
    state: { navigation: 1 },
    replaceState(...args) { calls.push(args) },
  }

  assert.equal(captureInviteToken('  secret-token  ', { history, storage }), true)
  assert.equal(storage.getItem(INVITE_KEY), 'secret-token')
  assert.deepEqual(calls[0].slice(1), ['', '/create'])
})

test('empty route tokens are rejected without erasing a restored invitation', () => {
  const storage = new MemoryStorage()
  storage.setItem(INVITE_KEY, 'restored-token')
  let replaced = false

  assert.equal(captureInviteToken('   ', {
    storage,
    history: { replaceState() { replaced = true } },
  }), false)
  assert.equal(getInviteToken(storage), 'restored-token')
  assert.equal(replaced, false)
})

test('invite credentials stay inside one tab and never use shared local storage', () => {
  const firstTab = new MemoryStorage()
  const secondTab = new MemoryStorage()
  captureInviteToken('tab-one', {
    storage: firstTab,
    history: { replaceState() {} },
  })

  assert.equal(getInviteAuthorization(firstTab), 'Invite tab-one')
  assert.equal(getInviteToken(secondTab), null)
  clearInviteToken(firstTab)
  assert.equal(getInviteAuthorization(firstTab), null)
})

test('public client injects only Invite auth and never redirects a public 401', () => {
  const request = read('../src/api/request.js')
  const clients = read('../src/api/clients.js')

  assert.match(request, /getAuthorization/)
  assert.match(request, /redirectOnUnauthorized\s*=\s*true/)
  assert.match(request, /redirectOnUnauthorized\s*&&/)
  assert.match(clients, /customerImageClient\s*=\s*createApiClient\(\{\s*baseURL:\s*['"]\/api\/customer-image['"]/s)
  assert.match(clients, /customerImagePublicClient\s*=\s*createApiClient\(\{[\s\S]*?getAuthorization:\s*getInviteAuthorization[\s\S]*?redirectOnUnauthorized:\s*false/)
})

test('invite interceptor ignores Ark JWT and a public 401 leaves Ark login untouched', async () => {
  const originalWindow = globalThis.window
  globalThis.window = { location: { href: '/create' } }
  try {
    const harness = loadCreateApiClient()
    harness.factory({
      baseURL: '/api/customer-image/public',
      getAuthorization: () => 'Invite invite-token',
      redirectOnUnauthorized: false,
    })
    const config = harness.handlers.request({ headers: {}, showLoading: false })
    assert.equal(config.headers.Authorization, 'Invite invite-token')

    const error = {
      config: { showLoading: false, suppressToast: true },
      response: { status: 401, data: { detail: 'invitation unavailable' } },
    }
    await assert.rejects(harness.handlers.responseFailure(error), value => value === error)
    assert.equal(harness.cleared(), 0)
    assert.equal(globalThis.window.location.href, '/create')
  } finally {
    globalThis.window = originalWindow
  }
})

test('public API covers context catalog logo assets and generation lifecycle silently', () => {
  const source = read('../src/api/customerImagePublic.js')

  for (const endpoint of [
    "'/context'",
    "'/products'",
    "'/logo'",
    "'/generations'",
    '`/generations/${generationId}`',
    '`/products/${productId}/assets/${assetId}/content`',
    '`/assets/${assetId}/content`',
  ]) assert.ok(source.includes(endpoint), `missing ${endpoint}`)
  assert.match(source, /responseType:\s*['"]blob['"]/)
  assert.match(source, /showLoading:\s*false/)
  assert.match(source, /suppressToast:\s*true/)
})
