import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import axios from 'axios'
import * as vue from 'vue'
import * as pinia from 'pinia'

const read = name => fs.readFileSync(new URL('../src/' + name, import.meta.url), 'utf8')
const outcome = promise => promise.then(value => ({ value }), error => ({ error }))

async function harness() {
  const values = new Map(), messages = [], pushes = [], gates = []
  const localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) }
  const context = vm.createContext({ localStorage, AbortController })
  const synthetic = exports => new vm.SyntheticModule(Object.keys(exports), function () { for (const [name, value] of Object.entries(exports)) this.setExport(name, value) }, { context })
  let auth
  const api = new vm.SourceTextModule(read('api/auth.js'), { context, importModuleDynamically: name => { assert.equal(name, '@/stores/auth'); return auth } })
  await api.link(name => {
    if (name === 'axios') return synthetic({ default: axios })
    if (name === 'element-plus') return synthetic({ ElMessage: { error: message => messages.push(message) } })
    throw new Error('Unexpected API dependency')
  })
  auth = new vm.SourceTextModule(read('stores/auth.js'), { context })
  await auth.link(name => {
    if (name === '@/api/auth') return api
    if (name === 'pinia') return synthetic(pinia)
    if (name === 'vue') return synthetic(vue)
    if (name === '@/router') return synthetic({ default: { async push(path) { pushes.push(path) } } })
    if (name === '@/utils/safeSessionStorage') return synthetic({ removeSessionItem() {} })
    throw new Error('Unexpected auth dependency')
  })
  await auth.evaluate()
  pinia.setActivePinia(pinia.createPinia())
  const store = auth.namespace.useAuthStore()
  api.namespace.authRequest.defaults.adapter = async config => {
    const gate = gates.shift()
    if (gate) return gate(config)
    const user = JSON.parse(config.data || '{}').username === 'B' ? 22 : 11
    return { config, headers: {}, status: 200, data: { access_token: 'synthetic-' + user, user: { id: user } } }
  }
  function defer({ abortAware = true } = {}) {
    let observed, release, rejected
    const started = new Promise(resolve => { observed = resolve })
    gates.push(config => new Promise((resolve, reject) => {
      release = () => resolve({ config, headers: {}, status: 200, data: { access_token: 'synthetic-old', user: { id: 11 } } })
      rejected = status => reject(new axios.AxiosError('Controlled transport error', 'ERR_BAD_REQUEST', config, null, { config, headers: {}, status, data: { detail: 'Controlled auth rejection' } }))
      if (abortAware) config.signal?.addEventListener('abort', () => reject(new axios.CanceledError('Controlled cancellation', config)), { once: true })
      observed(config)
    }))
    return { started, release: () => release(), reject: status => rejected(status) }
  }
  return { store, auth: auth.namespace, values, messages, pushes, defer }
}

for (const method of ['login', 'refresh', 'logout']) {
  test('real auth API cancels old ' + method + ' transport before B login', async () => {
    const h = await harness(); await h.store.login('A', 'synthetic-unused')
    const gate = h.defer()
    const pending = outcome(method === 'login' ? h.store.login('A', 'synthetic-unused') : method === 'refresh' ? h.store.refreshToken() : h.store.logout())
    const config = await gate.started
    assert.equal(config.withCredentials, true); assert.equal(config.signal.aborted, false)
    await h.store.login('B', 'synthetic-unused'); assert.equal(config.signal.aborted, true)
    const result = await pending
    if (method === 'logout') assert.equal(result.value, false)
    else assert.equal(result.error.code, 'ARK_AUTH_OPERATION_SUPERSEDED')
    assert.equal(h.store.user.id, 22); assert.equal(h.store.accessToken, 'synthetic-22')
    assert.equal(h.values.get('ark_access_token'), 'synthetic-22'); assert.deepEqual(h.messages, []); assert.deepEqual(h.pushes, [])
  })
}

test('real Axios still rejects aborted old refresh when adapter ignores abort', async () => {
  const h = await harness(); await h.store.login('A', 'synthetic-unused')
  const gate = h.defer({ abortAware: false }), pending = outcome(h.store.refreshToken()); await gate.started
  await h.store.login('B', 'synthetic-unused'); gate.release()
  assert.equal((await pending).error.code, 'ARK_AUTH_OPERATION_SUPERSEDED')
  assert.equal(h.store.user.id, 22); assert.equal(h.store.accessToken, 'synthetic-22'); assert.deepEqual(h.messages, [])
})

test('current real auth API login rejection retains normal error feedback', async () => {
  const h = await harness(), gate = h.defer(), pending = outcome(h.store.login('A', 'synthetic-unused')); await gate.started
  gate.reject(401); assert.equal((await pending).error.message, 'Controlled auth rejection')
  assert.deepEqual(h.messages, ['Controlled auth rejection']); assert.equal(h.store.accessToken, null); assert.equal(h.store.user, null)
})
