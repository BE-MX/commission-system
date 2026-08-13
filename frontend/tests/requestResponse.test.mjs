import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function loadResponseHandlers() {
  const source = readFileSync(new URL('../src/api/request.js', import.meta.url), 'utf8')
  const start = source.indexOf('export function createApiClient')
  const end = source.indexOf('const v1Client', start)
  const body = source.slice(start, end).replace('export function', 'function')
  const handlers = {}
  const messages = []
  const axios = {
    create() {
      return {
        interceptors: {
          request: { use() {} },
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
    `${body}; return createApiClient`,
  )(
    axios,
    { error(message) { messages.push(message) } },
    () => ({ show() {}, hide() {} }),
    () => null,
    () => {},
  )

  createApiClient({ baseURL: '/api' })
  return { handlers, messages }
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
