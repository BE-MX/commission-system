import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'

const source = readFileSync(new URL('../src/views/tracking/composables/useWaybillUpload.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '')
  .replace('export function useWaybillUpload', 'function useWaybillUpload')

function setup(upload = async () => ({ data: { waybill_no: '123456789012', recipient_name: 'Test' } })) {
  const listeners = new Map()
  const requests = []
  const messages = []
  const revoked = []
  let unmount
  const context = vm.createContext({
    ref: value => ({ value }), reactive: value => value,
    onMounted: fn => fn(), onBeforeUnmount: fn => { unmount = fn },
    document: {
      addEventListener: (name, fn) => listeners.set(name, fn),
      removeEventListener: (name, fn) => { if (listeners.get(name) === fn) listeners.delete(name) },
    },
    ElMessage: Object.fromEntries(['error', 'info', 'success', 'warning'].map(name => [name, msg => messages.push(msg)])),
    URL: { createObjectURL: () => `blob:${requests.length}`, revokeObjectURL: url => revoked.push(url) },
    FormData, console,
    uploadOCR: data => { requests.push(data); return upload(data) },
    checkWaybill: async () => ({ exists: false }),
    beijingCalendarDate: () => new Date('2026-09-17T00:00:00+08:00'),
  })
  const state = vm.runInContext(`${source}\nuseWaybillUpload()`, context)
  const paste = (files = [], editable = false) => {
    const event = {
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true },
      target: { closest: () => editable ? {} : null },
      clipboardData: { items: files.map(file => ({ kind: 'file', type: file.type, getAsFile: () => file })) },
    }
    return { event, done: listeners.get('paste')(event) }
  }
  return { state, paste, requests, messages, revoked, listeners, unmount: () => unmount() }
}

const picture = (type = 'image/png', size = 1) => new File([new Uint8Array(size)], 'clipboard.png', { type })

test('pasted image enters the same multipart OCR and preview flow as file selection', async () => {
  const h = setup()
  const { event, done } = h.paste([picture()])
  await done
  assert.equal(event.defaultPrevented, true)
  assert.equal(h.requests.length, 1)
  assert.equal(h.requests[0].get('file').type, 'image/png')
  assert.equal(h.state.mode.value, 'ocr')
  assert.equal(h.state.form.recipient_name, 'Test')
  assert.equal(h.state.ocrLoading.value, false)
  assert.ok(h.state.previewUrl.value)
  await h.state.handleFileChange({ raw: picture('image/jpeg') })
  assert.equal(h.requests.length, 2)
  assert.equal(h.revoked.length, 1)
})

test('unsupported and oversized images keep the current preview without uploading', async () => {
  const h = setup()
  await h.paste([picture()]).done
  const preview = h.state.previewUrl.value
  await h.paste([picture('image/gif')]).done
  await h.paste([picture('image/png', 10 * 1024 * 1024 + 1)]).done
  assert.equal(h.requests.length, 1)
  assert.equal(h.state.previewUrl.value, preview)
  assert.equal(h.messages.length, 2)
})

test('text, non-images, and editable fields retain native paste behavior', async () => {
  const h = setup()
  for (const [files, editable] of [[[], false], [[picture('application/pdf')], false], [[picture()], true]]) {
    const { event, done } = h.paste(files, editable)
    await done
    assert.equal(event.defaultPrevented, false)
  }
  assert.equal(h.requests.length, 0)
})

test('manual mode, submit, success dialog, and active OCR block paste and selected uploads', async () => {
  for (const [key, value] of [['mode', 'manual'], ['submitting', true], ['successVisible', true], ['ocrLoading', true]]) {
    const h = setup()
    h.state[key].value = value
    const { event, done } = h.paste([picture()])
    await done
    await h.state.handleFileChange({ raw: picture() })
    assert.equal(event.defaultPrevented, false)
    assert.equal(h.requests.length, 0)
  }
})

test('repeated paste while OCR is pending does not start another request', async () => {
  let resolve
  const h = setup(() => new Promise(done => { resolve = done }))
  const first = h.paste([picture()])
  await h.paste([picture()]).done
  assert.equal(h.requests.length, 1)
  resolve({ data: { recipient_name: 'First' } })
  await first.done
  assert.equal(h.state.form.recipient_name, 'First')
})

test('multiple images select one with feedback and unmount releases listener and preview', async () => {
  const h = setup()
  await h.paste([picture(), picture()]).done
  assert.equal(h.requests.length, 1)
  assert.equal(h.messages.length, 1)
  h.unmount()
  assert.equal(h.listeners.has('paste'), false)
  assert.equal(h.revoked.length, 1)
})

test('failed OCR can be retried by pasting another image', async () => {
  let count = 0
  const h = setup(async () => {
    if (++count === 1) throw new Error('Network')
    return { data: { recipient_name: 'Retry' } }
  })
  await h.paste([picture()]).done
  assert.ok(h.state.ocrError.value)
  await h.paste([picture('image/webp')]).done
  assert.equal(h.state.ocrError.value, '')
  assert.equal(h.state.form.recipient_name, 'Retry')
})
