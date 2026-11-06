import test from 'node:test'
import assert from 'node:assert/strict'
import { requestArchive, saveArchive } from '../public/customer-media/archive-download.js'

test('selection is sent once as unique IDs, and ZIP bytes are kept intact', async t => {
  const bytes = new Uint8Array([80, 75, 3, 4, 0, 1, 2])
  const calls = []
  t.mock.method(globalThis, 'fetch', async (...args) => {
    calls.push(args)
    return new Response(bytes, { headers: { 'content-type': 'application/zip' } })
  })
  const signal = new AbortController().signal
  const blob = await requestArchive([3, 2, 3], signal)
  assert.equal(calls.length, 1)
  assert.equal(calls[0][0], '/api/customer-media/portal/downloads/zip')
  assert.equal(calls[0][1].credentials, 'same-origin')
  assert.equal(calls[0][1].method, 'POST')
  assert.equal(calls[0][1].signal, signal)
  assert.deepEqual(JSON.parse(calls[0][1].body), { asset_ids: [3, 2] })
  assert.deepEqual(new Uint8Array(await blob.arrayBuffer()), bytes)
})

test('empty selection never sends a request', async t => {
  const fetch = t.mock.method(globalThis, 'fetch')
  await assert.rejects(requestArchive([]), /Select at least/)
  assert.equal(fetch.mock.callCount(), 0)
})

for (const [status, detail, message] of [
  [401, '请先登录', /sign in again/],
  [404, 'Some selected files are no longer available.', /no longer available/],
  [413, 'Selected files are too large for one ZIP.', /too large/],
  [503, 'Unable to prepare the ZIP right now.', /right now/],
  [422, [{ msg: 'invalid' }], /Unable to prepare/],
]) test(`HTTP ${status} is an error, never a downloadable ZIP`, async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response(JSON.stringify({ detail }), { status }))
  await assert.rejects(requestArchive([1]), message)
})

test('HTML/login response cannot be saved as a successful ZIP', async t => {
  t.mock.method(globalThis, 'fetch', async () => new Response('<html>Login</html>', { headers: { 'content-type': 'text/html' } }))
  await assert.rejects(requestArchive([1]), /could not be downloaded/)
})

test('aborted request is not retried automatically', async t => {
  const error = new DOMException('Aborted', 'AbortError')
  const fetch = t.mock.method(globalThis, 'fetch', async () => { throw error })
  await assert.rejects(requestArchive([1]), error)
  assert.equal(fetch.mock.callCount(), 1)
})

test('saving creates exactly one download and eventually releases the Blob URL', t => {
  const calls = [], link = { click: () => calls.push('click'), remove: () => calls.push('remove') }
  const originalDocument = globalThis.document, originalWindow = globalThis.window
  globalThis.document = { createElement: () => link, body: { appendChild: () => calls.push('append') } }
  let release
  globalThis.window = { setTimeout: callback => { release = callback } }
  t.after(() => { globalThis.document = originalDocument; globalThis.window = originalWindow })
  t.mock.method(URL, 'createObjectURL', () => 'blob:zip-fixture')
  const revoke = t.mock.method(URL, 'revokeObjectURL', () => {})
  saveArchive(new Blob(['zip']))
  assert.deepEqual(calls, ['append', 'click', 'remove'])
  assert.equal(link.download, 'LeShine-materials.zip')
  assert.equal(link.href, 'blob:zip-fixture')
  assert.equal(revoke.mock.callCount(), 0)
  release()
  assert.equal(revoke.mock.calls[0].arguments[0], 'blob:zip-fixture')
})
