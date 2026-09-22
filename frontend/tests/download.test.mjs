import test from 'node:test'
import assert from 'node:assert/strict'
import { downloadBlob } from '../src/utils/download.js'

const WORD_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'

function browser(t, { clickError } = {}) {
  const state = { blobs: [], links: [], revoked: [], timers: [], attached: new Set() }
  const originalWindow = globalThis.window
  const originalDocument = globalThis.document
  const originalTimeout = globalThis.setTimeout
  globalThis.window = { URL: {
    createObjectURL(blob) { state.blobs.push(blob); return `blob:test-${state.blobs.length}` },
    revokeObjectURL(url) { state.revoked.push(url) },
  } }
  globalThis.document = {
    createElement() {
      const link = { style: {}, click() {
        assert.ok(state.attached.has(link))
        state.links.push({ href: link.href, download: link.download })
        if (clickError) throw clickError
      } }
      return link
    },
    body: {
      appendChild(link) { state.attached.add(link) },
      removeChild(link) { state.attached.delete(link) },
    },
  }
  globalThis.setTimeout = (callback, delay) => { state.timers.push({ callback, delay }) }
  t.after(() => {
    globalThis.window = originalWindow
    globalThis.document = originalDocument
    globalThis.setTimeout = originalTimeout
  })
  return state
}

test('Word keeps bytes and MIME type; its URL survives the initial browser handoff', async t => {
  const state = browser(t)
  const blob = new Blob(['PK\x03\x04word-content'], { type: WORD_TYPE })
  downloadBlob({ data: blob, headers: {
    'content-disposition': `attachment; filename="fallback.docx"; filename*=UTF-8''${encodeURIComponent('出库单-0942.docx')}`,
  } })
  assert.equal(state.links[0].download, '出库单-0942.docx')
  assert.equal(state.blobs[0], blob)
  assert.equal(state.blobs[0].type, WORD_TYPE)
  assert.equal(await state.blobs[0].text(), 'PK\x03\x04word-content')
  assert.equal(state.attached.size, 0)
  assert.deepEqual(state.revoked, [])
  assert.equal(state.timers.length, 1)
  assert.ok(state.timers[0].delay >= 60000)
  state.timers[0].callback()
  assert.deepEqual(state.revoked, ['blob:test-1'])
})

test('missing response headers use the caller-provided Word filename', t => {
  const state = browser(t)
  downloadBlob({ data: new Blob(['word'], { type: WORD_TYPE }) }, '出库单-0942.docx')
  assert.equal(state.links[0].download, '出库单-0942.docx')
})

test('untyped payload inherits the response MIME type without changing bytes', async t => {
  const state = browser(t)
  const bytes = new Uint8Array([0, 80, 75, 255])
  downloadBlob({ data: new Blob([bytes]), headers: { 'content-type': WORD_TYPE } }, '出库单.docx')
  assert.equal(state.blobs[0].type, WORD_TYPE)
  assert.deepEqual(new Uint8Array(await state.blobs[0].arrayBuffer()), bytes)
})

test('malformed UTF-8 filename falls back to quoted plain filename', t => {
  const state = browser(t)
  downloadBlob({ data: new Blob(['word']), headers: {
    'content-disposition': 'attachment; filename*=UTF-8\'\'%E0%A4; filename="出库单; 100%.docx"',
  } }, '出库单.docx')
  assert.equal(state.links[0].download, '出库单; 100%.docx')
})

test('invalid filename encoding without a plain name uses the Word fallback', t => {
  const state = browser(t)
  downloadBlob({ data: new Blob(['word']), headers: {
    'content-disposition': "attachment; filename*=UTF-8''%XX",
  } }, '出库单.docx')
  assert.equal(state.links[0].download, '出库单.docx')
})

test('quoted filenames and Windows-forbidden path characters are cleaned', t => {
  const state = browser(t)
  downloadBlob({ data: new Blob(['word']), headers: {
    'content-disposition': 'attachment; FILENAME="出库单-09/42:美国.docx"',
  } })
  assert.equal(state.links[0].download, '出库单-09_42_美国.docx')
})

test('existing spreadsheet and PDF callers retain their names and types', t => {
  const state = browser(t)
  downloadBlob({ data: new Blob(['sheet']), headers: {} })
  downloadBlob({ data: new Blob(['pdf'], { type: 'application/pdf' }), headers: {
    'content-disposition': 'attachment; filename="inspection.pdf"',
  } })
  assert.equal(state.links[0].download, 'export.xlsx')
  assert.equal(state.links[1].download, 'inspection.pdf')
  assert.equal(state.blobs[1].type, 'application/pdf')
  state.timers.forEach(timer => timer.callback())
  assert.deepEqual(state.revoked, ['blob:test-1', 'blob:test-2'])
})

test('failed click still removes the temporary link and schedules URL cleanup', t => {
  const error = new Error('browser refused download')
  const state = browser(t, { clickError: error })
  assert.throws(() => downloadBlob({ data: new Blob(['word']), headers: {} }), error)
  assert.equal(state.attached.size, 0)
  state.timers[0].callback()
  assert.deepEqual(state.revoked, ['blob:test-1'])
})
