import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { AxiosHeaders } from 'axios'

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

function loadCustomerImagePublicApi() {
  const source = read('../src/api/customerImagePublic.js')
    .replace(/^import .*$/m, '')
    .replaceAll('export function', 'function')
  const calls = []
  const client = {
    get(...args) { calls.push(['get', ...args]); return args },
    post(...args) { calls.push(['post', ...args]); return args },
  }
  class InspectableFormData {
    values = []
    append(...args) { this.values.push(args) }
  }
  const api = new Function(
    'customerImagePublicClient',
    'FormData',
    `${source}; return {
      getContext, listProducts, uploadLogo, getProductAssetBlob, getAssetBlob,
      createGeneration, listGenerations, getGeneration,
    }`,
  )(client, InspectableFormData)
  return { api, calls }
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

test('referrer policy is parsed before any page resource can receive an invite URL', () => {
  const html = read('../index.html')
  const policy = html.indexOf('<meta name="referrer" content="no-referrer"')
  const firstResource = Math.min(
    ...['<link', '<script'].map(tag => {
      const index = html.indexOf(tag)
      return index < 0 ? Number.POSITIVE_INFINITY : index
    }),
  )

  assert.ok(policy >= 0, 'missing no-referrer policy in the initial HTML')
  assert.ok(policy < firstResource, 'referrer policy must precede every link and script')
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

test('invite interceptor replaces or removes case-insensitive Axios authorization headers', () => {
  const withInvite = loadCreateApiClient()
  withInvite.factory({
    baseURL: '/api/customer-image/public',
    getAuthorization: () => 'Invite invite-token',
    redirectOnUnauthorized: false,
  })
  const replacedHeaders = new AxiosHeaders({ authorization: 'Bearer leaked-ark-token' })
  withInvite.handlers.request({ headers: replacedHeaders, showLoading: false })
  assert.deepEqual({ ...replacedHeaders.toJSON() }, { authorization: 'Invite invite-token' })

  const withoutInvite = loadCreateApiClient()
  withoutInvite.factory({
    baseURL: '/api/customer-image/public',
    getAuthorization: () => null,
    redirectOnUnauthorized: false,
  })
  const clearedHeaders = new AxiosHeaders({ authorization: 'Bearer leaked-ark-token' })
  withoutInvite.handlers.request({ headers: clearedHeaders, showLoading: false })
  assert.equal(clearedHeaders.has('Authorization'), false)
})

test('default client injects Ark Bearer auth and redirects a 401 after clearing login', async () => {
  const originalWindow = globalThis.window
  globalThis.window = { location: { href: '/dashboard' } }
  try {
    const harness = loadCreateApiClient()
    harness.factory({ baseURL: '/api/v1' })
    const headers = new AxiosHeaders()
    harness.handlers.request({ headers, showLoading: false })
    assert.equal(headers.get('Authorization'), 'Bearer ark-token')

    const error = {
      config: { showLoading: false },
      response: { status: 401, data: { detail: 'expired' } },
    }
    await assert.rejects(harness.handlers.responseFailure(error), value => value === error)
    assert.equal(harness.cleared(), 1)
    assert.equal(globalThis.window.location.href, '/login')
  } finally {
    globalThis.window = originalWindow
  }
})

test('public API wrappers execute the exact silent method path body and blob contracts', () => {
  const { api, calls } = loadCustomerImagePublicApi()
  const logo = { name: 'logo.png' }
  const generation = { product_id: 7 }

  api.getContext()
  api.listProducts()
  api.uploadLogo(logo)
  api.getProductAssetBlob(7, 9)
  api.getAssetBlob(11)
  api.createGeneration(generation)
  api.listGenerations()
  api.getGeneration(13)

  assert.deepEqual(calls.map(([method, path]) => [method, path]), [
    ['get', '/context'],
    ['get', '/products'],
    ['post', '/logo'],
    ['get', '/products/7/assets/9/content'],
    ['get', '/assets/11/content'],
    ['post', '/generations'],
    ['get', '/generations'],
    ['get', '/generations/13'],
  ])
  assert.deepEqual(calls[2][2].values, [['file', logo]])
  assert.equal(calls[5][2], generation)
  for (const call of calls) {
    const config = call.at(-1)
    assert.equal(config.showLoading, false)
    assert.equal(config.suppressToast, true)
  }
  assert.equal(calls[3][2].responseType, 'blob')
  assert.equal(calls[4][2].responseType, 'blob')
})
