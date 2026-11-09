import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as vue from 'vue'
import * as draft from '../src/views/domestic_followup/followupDraft.js'

const source = readFileSync(new URL('../src/views/domestic_followup/composables/useFollowupComposer.js', import.meta.url), 'utf8')
  .replace(/^import[\s\S]*?from ['"][^'"]+['"]\r?\n/gm, '')
  .replace('export function useFollowupComposer', 'function useFollowupComposer')
const pending = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function harness() {
  const calls = [], errors = [], revoked = []
  const dependencies = {
    ref: vue.ref, reactive: vue.reactive, computed: vue.computed, watch: vue.watch,
    ...draft, onBeforeUnmount() {}, currentBeijingDate: () => '2026-11-02',
    followupApi: { dicts: async () => ({}), upload(file) { const request = pending(); calls.push({ file, ...request }); return request.promise } },
    apiError: (error, fallback) => error.response?.data?.detail || fallback,
    msgError: (message, error) => { if (!error._arkFeedbackHandled) errors.push(message); error._arkFeedbackHandled = true },
    msgWarning() {}, msgSuccessText() {},
    URL: { createObjectURL: file => `blob:${file.name}`, revokeObjectURL: url => revoked.push(url) },
  }
  const composer = new Function(...Object.keys(dependencies), `${source}\nreturn useFollowupComposer()`)(...Object.values(dependencies))
  return { composer, calls, errors, revoked }
}
const png = name => ({ name: `${name}.png`, type: 'image/png', size: 128 })
function uploadZone(composer) {
  const script = readFileSync(new URL('../src/components/AppUpload.vue', import.meta.url), 'utf8')
    .match(/<script setup>([\s\S]*?)<\/script>/)[1]
    .replace(/^import .*\r?\n/gm, '')
  const props = { transfer: true, accept: 'image/png,image/jpeg,image/webp', maxSizeMb: 10, limit: 9,
    get modelValue() { return composer.attachments.value.filter(row => !row.uploading) },
    uploadFn: composer.uploadAttachment }
  const deps = { ref: vue.ref, reactive: vue.reactive, computed: vue.computed,
    defineProps: () => props, defineEmits: () => () => {}, msgError() {} }
  return new Function(...Object.keys(deps), `${script}\nreturn { onPaste, onDrop, uploading }`)(...Object.values(deps))
}
const paste = (file, types = ['Files']) => ({
  clipboardData: { types, items: [{ kind: 'file', type: file.type, getAsFile: () => file }] },
  defaultPrevented: false, preventDefault() { this.defaultPrevented = true },
})

test('pasting a screenshot uploads once, blocks submit until it completes and retains the ID', async () => {
  const { composer: c, calls } = harness()
  const event = paste(png('clipboard'))
  const done = c.onPaste(event)
  c.onPaste(event)
  assert.equal(event.defaultPrevented, true)
  assert.equal(calls.length, 1)
  assert.equal(c.attachments.value.length, 1)
  assert.equal(c.canSubmit.value, false)
  calls[0].resolve({ id: 42, file_name: 'clipboard.png' })
  await done
  assert.equal(c.attachments.value[0].id, 42)
  assert.ok(c.canSubmit.value)
})

test('text and mixed text clipboard remain normal text in the composer form', () => {
  const { composer: c, calls } = harness()
  const event = paste(png('mixed'), ['text/plain', 'Files'])
  c.onPaste(event)
  assert.equal(event.defaultPrevented, false)
  assert.equal(calls.length, 0)
})

test('the shared screenshot area accepts mixed clipboard image once and keeps the composer attachment ID', async () => {
  const { composer: c, calls } = harness()
  const zone = uploadZone(c)
  const event = paste(png('screenshot'), ['Files', 'text/plain'])
  const request = zone.onPaste(event)
  c.onPaste(event)
  assert.equal(calls.length, 1)
  assert.equal(event.defaultPrevented, true)
  assert.equal(zone.uploading.value, true)
  calls[0].resolve({ id: 50 })
  await request
  assert.equal(zone.uploading.value, false)
  assert.equal(c.attachments.value[0].id, 50)
})

test('the shared screenshot area handles a drop and stops non-image files before the API', async () => {
  const { composer: c, calls } = harness()
  const zone = uploadZone(c)
  const event = { dataTransfer: { files: [png('drop'), { name: 'text.txt', type: 'text/plain', size: 1 }] }, preventDefault() {} }
  const request = zone.onDrop(event)
  assert.equal(calls.length, 1)
  calls[0].resolve({ id: 51 })
  await request
  assert.deepEqual(c.attachments.value.map(row => row.id), [51])
})

test('concurrent batches share nine slots, failed and removed files release slots', async () => {
  const { composer: c, calls, errors } = harness()
  const batch = c.addFiles(Array.from({ length: 8 }, (_, i) => png(i)))
  const next = c.addFiles([png('ninth'), png('overflow')])
  assert.equal(calls.length, 9)
  assert.equal(c.attachments.value.length, 9)
  calls[0].reject(new Error('offline'))
  calls.slice(1).forEach((call, i) => call.resolve({ id: i + 1 }))
  await Promise.all([batch, next])
  assert.equal(c.attachments.value.length, 8)
  assert.ok(errors.some(message => message.includes('最多上传')))
  assert.ok(errors.some(message => message.includes('上传失败')))
  c.removeAttachment(c.attachments.value[0])
  const retry = c.addFiles([png('retry'), png('replacement')])
  assert.equal(calls.length, 11)
  calls.slice(9).forEach((call, i) => call.resolve({ id: 20 + i }))
  await retry
  assert.equal(c.attachments.value.length, 9)
  assert.ok(c.attachments.value.every(row => row.id))
})

test('invalid image type and oversize files never reach the upload API', async () => {
  const { composer: c, calls, errors } = harness()
  await c.addFiles([{ ...png('large'), size: 10 * 1024 * 1024 + 1 }, { name: 'notes.txt', type: 'text/plain', size: 1 }])
  assert.equal(calls.length, 0)
  assert.equal(c.attachments.value.length, 0)
  assert.equal(errors.length, 2)
})

test('closing and reopening while files upload cannot attach old files to the new followup', async () => {
  const { composer: c, calls } = harness()
  await c.open()
  const old = c.addFiles([png('old-one'), png('old-two')])
  c.close()
  c.handleClosed()
  await c.open()
  const fresh = c.addFiles([png('fresh')])
  calls[0].resolve({ id: 1 })
  calls[1].resolve({ id: 2 })
  calls[2].resolve({ id: 3 })
  await Promise.all([old, fresh])
  assert.deepEqual(c.attachments.value.map(row => row.id), [3])
})

test('failed Axios uploads surface domain errors even when shared uploads suppress Axios toasts', async () => {
  const { composer: c, calls, errors } = harness()
  const request = c.uploadAttachment(png('failure'))
  const error = Object.assign(new Error('Request failed'), { isAxiosError: true, response: { data: { detail: '图片上传失败' } } })
  calls[0].reject(error)
  await assert.rejects(request)
  assert.deepEqual(errors, ['图片上传失败'])
  assert.equal(c.attachments.value.length, 0)
})
