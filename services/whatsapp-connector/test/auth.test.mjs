import assert from 'node:assert/strict'
import test from 'node:test'
import { authenticateWith, connectorConfig } from '../src/auth.js'

test('missing or blank key blocks startup and defaults to loopback when configured', () => {
  for (const key of [undefined, '', '   ']) {
    assert.throws(() => connectorConfig({ WHATSAPP_CONNECTOR_API_KEY: key }), /required/)
  }
  assert.equal(connectorConfig({ WHATSAPP_CONNECTOR_API_KEY: 'test-only' }).host, '127.0.0.1')
  assert.throws(() => authenticateWith(''), /requires/)
})

test('internal requests require the configured bearer key', () => {
  const authenticate = authenticateWith('test-only')
  for (const header of [undefined, 'Bearer wrong', 'test-only', 'Bearer test-only']) {
    let nextCalls = 0
    let status
    const response = { status(code) { status = code; return this }, json() {} }
    authenticate({ headers: { authorization: header } }, response, () => nextCalls++)
    assert.equal(nextCalls, header === 'Bearer test-only' ? 1 : 0)
    assert.equal(status, header === 'Bearer test-only' ? undefined : 401)
  }
})
