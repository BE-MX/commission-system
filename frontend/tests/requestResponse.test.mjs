import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import realAxios from 'axios'

function loadResponseHandlers(axiosOverride) {
  const source = readFileSync(new URL('../src/api/request.js', import.meta.url), 'utf8')
  const start = source.indexOf('export function createApiClient')
  const end = source.indexOf('const v1Client', start)
  const body = source.slice(start, end).replace('export function', 'function')
  const handlers = {}
  const messages = []
  const loadingState = { count: 0, show() { this.count++ }, hide() { this.count-- } }
  const axios = {
    isCancel: error => error.code === 'ERR_CANCELED',
    create() {
      return {
        interceptors: {
          request: { use(handler) { handlers.request = handler } },
          response: {
            use(success, failure) {
              handlers.success = success
              handlers.failure = failure
            },
          },
        },
      }
    },
  }
  const createApiClient = new Function(
    'axios',
    'ElMessage',
    'useLoading',
    'getAccessToken',
    'clearAuthState',
    'loading',
    `${body}; return createApiClient`,
  )(
    axiosOverride || axios,
    { error(message) { messages.push(typeof message === 'string' ? message : message.message) } },
    () => ({ show() {}, hide() {} }),
    () => null,
    () => {},
    loadingState,
  )

  const client = createApiClient({ baseURL: '/api' })
  return { handlers, messages, loadingState, client }
}

test('response interceptor accepts a 202 business envelope', async () => {
  const { handlers, messages } = loadResponseHandlers()
  const envelope = { code: 202, message: 'ok', data: { status: 'pending' } }

  const result = await handlers.success({
    config: { showLoading: false },
    data: envelope,
    status: 202,
  })

  assert.equal(result, envelope)
  assert.deepEqual(messages, [])
})

test('suppressed business failures reject without a duplicate toast', async () => {
  const { handlers, messages } = loadResponseHandlers()
  await assert.rejects(handlers.success({
    config: { showLoading: false, suppressToast: true },
    data: { code: 422, message: 'Invalid choice' },
  }), /Invalid choice/)
  assert.deepEqual(messages, [])
})

test('canceled requests release their loading slot without a network error toast', async () => {
  const { handlers, messages, loadingState } = loadResponseHandlers()
  const config = handlers.request({ headers: {} })
  const error = { code: 'ERR_CANCELED', config }
  await assert.rejects(handlers.failure(error), error)
  assert.equal(loadingState.count, 0)
  assert.deepEqual(messages, [])
})

test('an error without a request config cannot hide another pending request', async () => {
  const { handlers, loadingState } = loadResponseHandlers()
  const config = handlers.request({ headers: {} })
  await assert.rejects(handlers.failure(new Error('setup failed')), /setup failed/)
  assert.equal(loadingState.count, 1)
  handlers.success({ config, data: { code: 200 } })
  assert.equal(loadingState.count, 0)
})

test('real Axios serialization failure releases only its own loading slot', async () => {
  const { client, loadingState } = loadResponseHandlers(realAxios)
  let resolvePending
  client.defaults.adapter = config => new Promise(resolve => {
    resolvePending = () => resolve({ config, status: 200, data: { code: 200 }, headers: {} })
  })
  const pending = client.get('/pending')
  await new Promise(resolve => setImmediate(resolve))
  assert.equal(loadingState.count, 1)
  await assert.rejects(client.post('/invalid', { value: 1n }), TypeError)
  assert.equal(loadingState.count, 1)
  resolvePending()
  await pending
  assert.equal(loadingState.count, 0)
})

test('response interceptor still rejects non-2xx business codes', async () => {
  const { handlers, messages } = loadResponseHandlers()
  const response = code => handlers.success({
    config: { showLoading: false },
    data: { code, message: '业务校验失败' },
    status: 200,
  })

  await assert.rejects(response(422), /业务校验失败/)
  await assert.rejects(response('invalid'), /业务校验失败/)
  assert.deepEqual(messages, ['业务校验失败', '业务校验失败'])
})
