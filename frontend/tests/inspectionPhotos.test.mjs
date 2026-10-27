import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { computed, nextTick, reactive, ref, watch } from 'vue'

const source = fs.readFileSync(new URL('../src/views/shipping/components/InspectionPhotos.vue', import.meta.url), 'utf8')
  .match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
const flush = async () => { await nextTick(); for (let i = 0; i < 8; i++) await Promise.resolve() }
function harness(photos = [{ id: 1, file_path: 'a.jpg' }, { id: 2, file_path: 'b.jpg' }]) {
  const props = reactive({ photos, items: [] }), calls = [], revoked = [], stops = [], unmounts = []
  const request = kind => (path, config = {}) => new Promise((resolve, reject) => calls.push({ kind, path, config, resolve, reject }))
  const context = vm.createContext({
    computed, ref, AbortController, defineProps: () => props,
    watch: (...args) => { const stop = watch(...args); stops.push(stop); return stop },
    onBeforeUnmount: fn => unmounts.push(fn),
    fetchImageBlobUrl: request('original'), fetchImagePreviewBlobUrl: request('preview'),
    URL: { revokeObjectURL: url => revoked.push(url) },
  })
  vm.runInContext(source + '\nthis.state = {displayPhotos, urls, openOriginal: typeof openOriginal === "function" ? openOriginal : null, retryPhoto: typeof retryPhoto === "function" ? retryPhoto : null, closeOriginal: typeof closeOriginal === "function" ? closeOriginal : null, originalUrl: typeof originalUrl !== "undefined" ? originalUrl : null, openPreview: typeof openPreview === "function" ? openPreview : null, previewUrls: typeof previewUrls !== "undefined" ? previewUrls : null}', context)
  return { props, calls, revoked, ...context.state, stop() { stops.forEach(fn => fn()); unmounts.forEach(fn => fn()) } }
}

test('first completed photo is visible while another photo is still pending', async () => {
  const h = harness()
  try {
    h.calls[0].resolve('blob:first'); await flush()
    assert.equal(h.displayPhotos.value.find(photo => photo.id === 1)?.url, 'blob:first')
    assert.equal(h.calls.length, 2)
  } finally { h.stop() }
})

test('opening a large inspection requests only previews with bounded concurrency', () => {
  const h = harness(Array.from({ length: 20 }, (_, i) => ({ id: i, file_path: `${i}.jpg` })))
  try {
    assert.ok(h.calls.length > 0 && h.calls.length <= 3)
    assert.ok(h.calls.every(call => call.kind === 'preview'))
  } finally { h.stop() }
})

test('failed photo remains retryable without hiding the successful photo', async () => {
  const h = harness()
  try {
    h.calls[0].resolve('blob:first'); h.calls[1].reject(new Error('timeout')); await flush()
    const failed = h.displayPhotos.value.find(photo => photo.id === 2)
    assert.equal(failed.failed, true)
    const retry = h.retryPhoto(failed)
    assert.equal(h.calls[2].path, 'b.jpg')
    h.calls[2].resolve('blob:retried'); await retry; await flush()
    assert.equal(failed.url, 'blob:retried')
    assert.equal(h.displayPhotos.value[0].url, 'blob:first')
  } finally { h.stop() }
})

test('queue starts the next preview as each slot completes', async () => {
  const h = harness(Array.from({ length: 8 }, (_, i) => ({ id: i, file_path: `${i}.jpg` })))
  try {
    assert.equal(h.calls.length, 3)
    h.calls[1].resolve('blob:second'); await flush()
    assert.equal(h.calls.length, 4)
    assert.equal(h.displayPhotos.value[1].url, 'blob:second')
    assert.equal(h.calls[3].path, '3.jpg')
  } finally { h.stop() }
})

test('photo finishing earlier in display order cannot switch an open gallery', async () => {
  const h = harness()
  try {
    h.calls[1].resolve('blob:second'); await flush()
    h.openPreview(h.displayPhotos.value[1])
    assert.equal(h.previewUrls.value[0], 'blob:second')
    h.calls[0].resolve('blob:first'); await flush()
    assert.equal(h.previewUrls.value.length, 1)
    assert.equal(h.previewUrls.value[0], 'blob:second')
    assert.equal(h.urls.value.length, 2)
  } finally { h.stop() }
})

test('switching records aborts pending requests and discards late photos', async () => {
  const h = harness()
  try {
    h.calls[0].resolve('blob:first'); await flush()
    h.props.photos = [{ id: 9, file_path: 'new.jpg' }]; await flush()
    assert.equal(h.calls[1].config.signal.aborted, true)
    h.calls[1].resolve('blob:late'); h.calls[2].resolve('blob:new'); await flush()
    assert.equal(h.displayPhotos.value.length, 1)
    assert.equal(h.displayPhotos.value[0].url, 'blob:new')
    assert.ok(h.revoked.includes('blob:first'))
    assert.ok(h.revoked.includes('blob:late'))
  } finally { h.stop() }
})

test('originals load only on demand and keep an independent longer timeout', async () => {
  const h = harness([{ id: 1, file_path: 'large.jpg' }])
  try {
    h.calls[0].resolve('blob:small'); await flush()
    assert.equal(h.calls.filter(call => call.kind === 'original').length, 0)
    const load = h.openOriginal(h.displayPhotos.value[0])
    assert.equal(h.calls[1].kind, 'original')
    assert.equal(h.calls[1].config.timeout, 300000)
    assert.equal(h.calls[1].config.showLoading, false)
    h.calls[1].resolve('blob:original'); await load
    assert.equal(h.originalUrl.value, 'blob:original')
    h.closeOriginal()
    assert.ok(h.revoked.includes('blob:original'))
    assert.equal(h.displayPhotos.value[0].url, 'blob:small')
  } finally { h.stop() }
})

test('unmount aborts original download and releases late object URLs', async () => {
  const h = harness([{ id: 1, file_path: 'large.jpg' }])
  h.calls[0].resolve('blob:small'); await flush()
  const load = h.openOriginal(h.displayPhotos.value[0])
  h.stop()
  assert.equal(h.calls[1].config.signal.aborted, true)
  h.calls[1].resolve('blob:late-original'); await load
  assert.equal(h.originalUrl.value, '')
  assert.ok(h.revoked.includes('blob:small'))
  assert.ok(h.revoked.includes('blob:late-original'))
})

test('original failure exposes retry without losing preview', async () => {
  const h = harness([{ id: 1, file_path: 'large.jpg' }])
  try {
    h.calls[0].resolve('blob:small'); await flush()
    const photo = h.displayPhotos.value[0], load = h.openOriginal(photo)
    h.calls[1].reject(new Error('network')); await load
    assert.equal(photo.originalFailed, true)
    assert.equal(photo.url, 'blob:small')
    const retry = h.openOriginal(photo)
    h.calls[2].resolve('blob:original'); await retry
    assert.equal(h.originalUrl.value, 'blob:original')
  } finally { h.stop() }
})

test('preview transport explicitly requests a derivative and keeps abort signal', async () => {
  const apiSource = fs.readFileSync(new URL('../src/api/shipping.js', import.meta.url), 'utf8')
    .replace(/^import .*$/gm, '').replace(/^export /gm, '')
  const calls = [], signal = new AbortController().signal
  const context = vm.createContext({
    shippingClient: { get: async (...args) => { calls.push(args); return { data: 'bytes' } } },
    URL: { createObjectURL: () => 'blob:preview' },
  })
  vm.runInContext(apiSource + '\nthis.preview = fetchImagePreviewBlobUrl', context)
  assert.equal(await context.preview('private/photo.jpg', { signal }), 'blob:preview')
  assert.equal(calls[0][0], '/images/private/photo.jpg')
  assert.equal(calls[0][1].params.preview, true)
  assert.equal(calls[0][1].signal, signal)
  assert.equal(calls[0][1].responseType, 'blob')
  assert.equal(calls[0][1].showLoading, false)
})
