import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import realAxios from 'axios'
import * as vue from 'vue'
import * as pinia from 'pinia'

const read = name => fs.readFileSync(new URL('../src/' + name, import.meta.url), 'utf8')
const tick = () => new Promise(resolve => setImmediate(resolve))

async function harness({ path = '/invoice/manage', search = '', hash = '' } = {}) {
  const stored = new Map(), effects = { redirects: [], pushes: [], messages: [], loading: 0 }
  const localStorage = { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, String(value)), removeItem: key => stored.delete(key) }
  const location = { pathname: path, search, hash, set href(value) { effects.redirects.push(value) } }
  const identities = { A: { id: 11, token: 'synthetic-A' }, B: { id: 22, token: 'synthetic-B' } }
  let refreshed = 'synthetic-refreshed'
  const authApi = {
    async login({ username }) { const value = identities[username]; return { access_token: value.token, user: { id: value.id, roles: ['sales'], permissions: ['invoice:read'] } } },
    async refresh() { return { access_token: refreshed } },
    async logout() {},
    async getMe() { return { id: 11 } },
  }
  const context = vm.createContext({ AbortController, localStorage, window: { location } })
  const synthetic = exports => new vm.SyntheticModule(Object.keys(exports), function () { for (const [name, value] of Object.entries(exports)) this.setExport(name, value) }, { context })
  const auth = new vm.SourceTextModule(read('stores/auth.js'), { context })
  const authImports = { pinia, vue, '@/api/auth': { authApi }, '@/router': { default: { async push(target) { effects.pushes.push(target) } } }, '@/utils/safeSessionStorage': { removeSessionItem() {} } }
  await auth.link(name => { assert.ok(authImports[name]); return synthetic(authImports[name]) })
  await auth.evaluate()
  const fx = new vm.SourceTextModule(read('router/fxSettlementRoute.js'), { context })
  await fx.link(() => { throw new Error('Unexpected fx dependency') }); await fx.evaluate()
  const request = new vm.SourceTextModule(read('api/request.js'), { context })
  const imports = {
    axios: { default: realAxios },
    'element-plus': { ElMessage: { error(value) { effects.messages.push(typeof value === 'string' ? value : value.message) } } },
    '@/composables/useLoading': { useLoading: () => ({ show() { effects.loading++ }, hide() { effects.loading-- } }) },
  }
  await request.link(name => {
    if (name === '@/stores/auth') return auth
    if (name === '@/router/fxSettlementRoute') return fx
    assert.ok(imports[name]); return synthetic(imports[name])
  })
  await request.evaluate()
  pinia.setActivePinia(pinia.createPinia())
  const store = auth.namespace.useAuthStore()
  const clients = []
  function client(options = {}) {
    const result = request.namespace.createApiClient({ baseURL: '/api/invoice', ...options })
    const queue = []
    result.defaults.adapter = config => new Promise((resolve, reject) => queue.push({ config, resolve, reject }))
    clients.push(result)
    return {
      async start(config = {}) {
        const pending = result.get('/controlled-read', config)
        const outcome = pending.then(value => ({ value }), error => ({ error }))
        await tick()
        assert.equal(queue.length, 1)
        const gate = queue.shift()
        return {
          config: gate.config,
          async reject(status = 401, detail = 'Not authenticated', withoutConfig = false) {
            const error = new realAxios.AxiosError('Controlled rejection', 'ERR_BAD_REQUEST', withoutConfig ? undefined : gate.config, null,
              { status, data: { detail }, headers: {}, config: withoutConfig ? undefined : gate.config })
            gate.reject(error)
            const settled = await outcome
            assert.equal(settled.error, error)
          },
          async succeed() { gate.resolve({ config: gate.config, status: 200, data: { code: 200, data: { visible: true } }, headers: {} }); const settled = await outcome; assert.equal(settled.value.code, 200) },
        }
      },
    }
  }
  function deferAuth(method) {
    const original = authApi[method]
    let release, reject, started
    const observed = new Promise(resolve => { started = resolve })
    authApi[method] = (...args) => {
      authApi[method] = original
      started(args)
      return new Promise((resolve, fail) => { release = resolve; reject = fail })
    }
    return { observed, succeed: value => release(value), fail: error => reject(error) }
  }
  async function initializeApp() {
    let mounted
    const source = read('App.vue').match(/<script setup>([\s\S]*?)<\/script>/)[1]
    const app = new vm.SourceTextModule(source, { context })
    await app.link(name => {
      if (name === '@/stores/auth') return auth
      if (name === 'vue') return synthetic({ ...vue, onMounted: fn => { mounted = fn } })
      if (name === '@/components/GlobalLoading.vue') return synthetic({ default: {} })
      throw new Error('Unexpected App dependency')
    })
    await app.evaluate()
    return mounted()
  }
  return { store, effects, stored, auth: auth.namespace, client, deferAuth, initializeApp, setRefresh: value => { refreshed = value }, async login(name = 'A') { await store.login(name, 'synthetic-unused') } }
}

function preserved(h, identity = 'B') {
  assert.equal(h.auth.getAccessToken(), 'synthetic-' + identity)
  assert.equal(h.stored.get('ark_access_token'), 'synthetic-' + identity)
  assert.equal(h.store.user.id, identity === 'B' ? 22 : 11)
  assert.deepEqual(h.effects.redirects, [])
  assert.deepEqual(h.effects.messages, [])
  assert.equal(h.effects.loading, 0)
}

for (const status of [401, 403]) {
  test('current auth ' + status + ' still clears token and redirects', async () => {
    const h = await harness(); await h.login(); const pending = await h.client().start()
    assert.equal(pending.config.headers.get('Authorization'), 'Bearer synthetic-A')
    await pending.reject(status)
    assert.equal(h.auth.getAccessToken(), null); assert.equal(h.stored.has('ark_access_token'), false)
    assert.deepEqual(h.effects.redirects, ['/login']); assert.deepEqual(h.effects.messages, []); assert.equal(h.effects.loading, 0)
  })
  test('old auth ' + status + ' after another login preserves new account', async () => {
    const h = await harness(); await h.login(); const pending = await h.client().start()
    await h.login('B'); await pending.reject(status); preserved(h)
  })
}

test('old auth failure after refresh preserves fresh token', async () => {
  const h = await harness(); await h.login(); const pending = await h.client().start()
  await h.store.refreshToken(); await pending.reject()
  assert.equal(h.auth.getAccessToken(), 'synthetic-refreshed'); assert.equal(h.store.accessToken, 'synthetic-refreshed')
  assert.deepEqual(h.effects.redirects, []); assert.deepEqual(h.effects.messages, []); assert.equal(h.effects.loading, 0)
})

test('old auth failure after actual store logout has no second redirect', async () => {
  const h = await harness(); await h.login(); const pending = await h.client().start()
  await h.store.logout(); await pending.reject()
  assert.equal(h.auth.getAccessToken(), null); assert.equal(h.store.user, null)
  assert.deepEqual(h.effects.pushes, ['/login']); assert.deepEqual(h.effects.redirects, []); assert.deepEqual(h.effects.messages, []); assert.equal(h.effects.loading, 0)
})

test('same token A B A login cycle does not revive old failure authority', async () => {
  const h = await harness(); await h.login(); const pending = await h.client().start()
  await h.login('B'); await h.login('A'); await pending.reject(); preserved(h, 'A')
})

test('same token refresh still invalidates older failure authority', async () => {
  const h = await harness(); await h.login(); const pending = await h.client().start()
  h.setRefresh('synthetic-A'); await h.store.refreshToken(); await pending.reject(); preserved(h, 'A')
})

test('anonymous request cannot clear a subsequently logged in account', async () => {
  const h = await harness(); const pending = await h.client().start()
  assert.equal(pending.config.headers.has('Authorization'), false)
  await h.login('B'); await pending.reject(); preserved(h)
})

test('current anonymous 401 still redirects to login', async () => {
  const h = await harness(); const pending = await h.client().start(); await pending.reject()
  assert.deepEqual(h.effects.redirects, ['/login']); assert.deepEqual(h.effects.messages, []); assert.equal(h.effects.loading, 0)
})

test('auth failure with unbound config does not clear current account', async () => {
  const h = await harness(); await h.login('B'); const pending = await h.client().start({ showLoading: false }); await pending.reject(401, 'Not authenticated', true); preserved(h)
})

test('current ordinary permission 403 remains visible without clearing login', async () => {
  const h = await harness(); await h.login(); const pending = await h.client().start(); await pending.reject(403, 'Permission denied')
  assert.equal(h.auth.getAccessToken(), 'synthetic-A'); assert.deepEqual(h.effects.redirects, []); assert.deepEqual(h.effects.messages, ['Permission denied']); assert.equal(h.effects.loading, 0)
})

test('client opt out preserves current login after auth failure', async () => {
  const h = await harness(); await h.login('B'); const pending = await h.client({ redirectOnUnauthorized: false }).start({ suppressToast: true }); await pending.reject(); preserved(h)
})

test('per request opt out preserves current login after auth failure', async () => {
  const h = await harness(); await h.login('B'); const pending = await h.client().start({ redirectOnUnauthorized: false, suppressToast: true }); await pending.reject(403); preserved(h)
})

test('current fx auth failure preserves route query and fragment', async () => {
  const h = await harness({ path: '/fx-settlement', search: '?view=owned', hash: '#receipt' }); await h.login()
  const pending = await h.client().start(); await pending.reject()
  assert.deepEqual(h.effects.redirects, ['/login?redirect=' + encodeURIComponent('/fx-settlement?view=owned#receipt')]); assert.equal(h.effects.loading, 0)
})

test('late invitation failure respects rotating custom authorization', async () => {
  const h = await harness(); await h.login('B'); let authorization = 'Bearer synthetic-invite-A'
  const pending = await h.client({ getAuthorization: () => authorization }).start()
  assert.equal(pending.config.headers.get('Authorization'), authorization)
  authorization = 'Bearer synthetic-invite-B'; await pending.reject(); preserved(h)
})

test('parallel current failures invalidate authentication only once', async () => {
  const h = await harness(); await h.login(); const client = h.client()
  const first = await client.start(), second = await client.start()
  assert.equal(h.effects.loading, 2); await first.reject(); assert.equal(h.effects.loading, 1); await second.reject()
  assert.deepEqual(h.effects.redirects, ['/login']); assert.deepEqual(h.effects.messages, []); assert.equal(h.effects.loading, 0)
})

test('old failure releases its slot while current success remains pending', async () => {
  const h = await harness(); await h.login(); const client = h.client(); const old = await client.start()
  await h.login('B'); const current = await client.start(); await old.reject()
  assert.equal(h.effects.loading, 1); assert.equal(h.auth.getAccessToken(), 'synthetic-B'); assert.deepEqual(h.effects.redirects, []); assert.deepEqual(h.effects.messages, [])
  await current.succeed(); preserved(h)
})

function captured(promise) { return promise.then(value => ({ value }), error => ({ error })) }
function superseded(h, result) { assert.equal(result.error?.code, 'ARK_AUTH_OPERATION_SUPERSEDED') }

for (const method of ['refresh', 'logout', 'login', 'getMe']) {
  for (const failure of [false, true]) {
    test('late ' + method + (failure ? ' failure' : ' success') + ' after B login preserves B', async () => {
      const h = await harness(); await h.login()
      const deferred = h.deferAuth(method)
      const operation = method === 'refresh' ? h.store.refreshToken() : method === 'logout' ? h.store.logout('/controlled-login') : method === 'login' ? h.store.login('A', 'synthetic-unused') : h.store.fetchMe()
      const outcome = captured(operation), args = await deferred.observed
      await h.login('B')
      if (failure) deferred.fail(new Error('Controlled old transport failure'))
      else deferred.succeed(method === 'getMe' ? { id: 11 } : { access_token: 'synthetic-A', user: { id: 11 } })
      const result = await outcome
      preserved(h); assert.deepEqual(h.effects.pushes, [])
      if (method !== 'getMe') {
        const options = method === 'login' ? args[1] : args[0]
        assert.equal(options?.signal?.aborted, true)
      }
      if (method === 'logout') assert.equal(result.value, false)
      else superseded(h, result)
      preserved(h); assert.deepEqual(h.effects.pushes, [])
    })
  }
}

test('newer same generation me response wins before old success', async () => {
  const h = await harness(); await h.login()
  const old = h.deferAuth('getMe'), first = captured(h.store.fetchMe()); await old.observed
  const fresh = h.deferAuth('getMe'), second = captured(h.store.fetchMe()); await fresh.observed
  fresh.succeed({ id: 11, name: 'current' }); assert.equal((await second).value.name, 'current')
  old.succeed({ id: 11, name: 'old' }); superseded(h, await first)
  assert.equal(h.store.user.name, 'current'); preserved(h, 'A')
})

test('old refresh cannot survive same token A B A login cycle', async () => {
  const h = await harness(); await h.login()
  const deferred = h.deferAuth('refresh'), outcome = captured(h.store.refreshToken()); await deferred.observed
  await h.login('B'); await h.login('A'); deferred.succeed({ access_token: 'synthetic-old-refreshed' })
  superseded(h, await outcome); preserved(h, 'A')
})

for (const method of ['refresh', 'login']) {
  test('clearAuthState invalidates pending ' + method + ' success', async () => {
    const h = await harness(); await h.login()
    const deferred = h.deferAuth(method), outcome = captured(method === 'refresh' ? h.store.refreshToken() : h.store.login('B', 'synthetic-unused'))
    const args = await deferred.observed
    h.auth.clearAuthState()
    deferred.succeed({ access_token: 'synthetic-B', user: { id: 22 } }); superseded(h, await outcome)
    assert.equal(h.auth.getAccessToken(), null); assert.equal(h.stored.has('ark_access_token'), false)
    assert.equal((method === 'refresh' ? args[0] : args[1])?.signal?.aborted, true)
  })
}

test('current refresh failure keeps original error and existing account', async () => {
  const h = await harness(); await h.login()
  const deferred = h.deferAuth('refresh'), outcome = captured(h.store.refreshToken()); await deferred.observed
  const error = new Error('Controlled current failure'); deferred.fail(error)
  assert.equal((await outcome).error, error); preserved(h, 'A')
})

test('current logout failure still clears state and uses caller target', async () => {
  const h = await harness(); await h.login()
  const deferred = h.deferAuth('logout'), outcome = captured(h.store.logout('/controlled-login')); await deferred.observed
  deferred.fail(new Error('Controlled current failure')); assert.equal((await outcome).error, undefined)
  assert.equal(h.auth.getAccessToken(), null); assert.equal(h.store.accessToken, null); assert.equal(h.store.user, null)
  assert.deepEqual(h.effects.pushes, ['/controlled-login'])
})

for (const failure of [false, true]) {
  test('actual App bootstrap old me ' + (failure ? 'failure' : 'success') + ' does not recover after B login', async () => {
    const h = await harness(); await h.login(); h.store.user = null
    const deferred = h.deferAuth('getMe'), outcome = captured(h.initializeApp()); await deferred.observed
    await h.login('B')
    if (failure) deferred.fail(new Error('Controlled old failure'))
    else deferred.succeed({ id: 11 })
    assert.equal((await outcome).error, undefined); preserved(h); assert.deepEqual(h.effects.pushes, [])
  })
}

test('actual anonymous App bootstrap old refresh failure preserves later B login', async () => {
  const h = await harness(), deferred = h.deferAuth('refresh'), outcome = captured(h.initializeApp()); await deferred.observed
  await h.login('B'); deferred.fail(new Error('Controlled old failure'))
  assert.equal((await outcome).error, undefined); preserved(h)
})

test('actual App fallback old refresh failure does not clear later B login', async () => {
  const h = await harness(); await h.login(); h.store.user = null
  const me = h.deferAuth('getMe'), refresh = h.deferAuth('refresh'), outcome = captured(h.initializeApp()); await me.observed
  me.fail(new Error('Controlled expired me')); await refresh.observed
  await h.login('B'); refresh.fail(new Error('Controlled expired old refresh'))
  assert.equal((await outcome).error, undefined); preserved(h)
})

for (const method of ['login', 'refresh', 'getMe']) {
  for (let delay = 0; delay <= 6; delay++) {
    test('write fence ' + method + ' microtask delay ' + delay + ' preserves newer intent', async () => {
      const h = await harness(); await h.login()
      const old = h.deferAuth(method)
      const first = captured(method === 'login' ? h.store.login('A', 'synthetic-unused') : method === 'refresh' ? h.store.refreshToken() : h.store.fetchMe())
      await old.observed
      const next = h.deferAuth('login')
      let second, committedBeforeB
      old.succeed(method === 'getMe' ? { id: 999 } : { access_token: 'synthetic-obsolete', user: { id: 999 } })
      const beginB = remaining => {
        if (remaining > 0) { queueMicrotask(() => beginB(remaining - 1)); return }
        committedBeforeB = method === 'getMe' ? h.store.user?.id === 999 : h.store.accessToken === 'synthetic-obsolete'
        second = captured(h.store.login('B', 'synthetic-unused'))
      }
      queueMicrotask(() => beginB(delay))
      await next.observed
      const result = await first
      const snapshot = { id: h.store.user?.id, token: h.store.accessToken }
      next.succeed({ access_token: 'synthetic-B', user: { id: 22 } })
      const later = await second
      if (!committedBeforeB) {
        superseded(h, result)
        assert.deepEqual(snapshot, { id: 11, token: 'synthetic-A' })
      } else {
        assert.equal(result.error, undefined)
      }
      assert.equal(later.error, undefined); preserved(h)
    })
  }
}
