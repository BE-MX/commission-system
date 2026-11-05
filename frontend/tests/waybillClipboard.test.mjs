import { feedbackFixture } from './helpers/feedbackFixture.mjs'
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { ref, reactive, watch } from 'vue'

const source = readFileSync(new URL('../src/views/tracking/composables/useWaybillUpload.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '')
  .replace('export function useWaybillUpload', 'function useWaybillUpload')

function setup(upload = async () => ({ data: { waybill_no: '123456789012', recipient_name: 'Test' } }), options = {}) {
  const listeners = new Map()
  const requests = []
  const messages = []
  const revoked = []
  const checks = []
  const submissions = []
  let unmount
  const context = vm.createContext({
    ref, reactive, watch,
    onMounted: fn => fn(), onBeforeUnmount: fn => { unmount = fn },
    document: {
      addEventListener: (name, fn) => listeners.set(name, fn),
      removeEventListener: (name, fn) => { if (listeners.get(name) === fn) listeners.delete(name) },
    },
    ElMessage: Object.fromEntries(['error', 'info', 'success', 'warning'].map(name => [name, msg => messages.push(msg)])),
    URL: { createObjectURL: () => `blob:${requests.length}`, revokeObjectURL: url => revoked.push(url) },
    FormData, console,
    uploadOCR: data => { requests.push(data); return upload(data) },
    checkWaybill: async no => { checks.push(no); return options.check ? options.check(no) : { exists: false } },
    createWaybill: async data => { submissions.push({ ...data }); return options.submit ? options.submit(data) : { data } },
    composableOptions: options.composableOptions || {},
    beijingCalendarDate: () => new Date('2026-09-17T00:00:00+08:00'),
  })
  Object.assign(context, feedbackFixture(context))
  const state = vm.runInContext(`${source}\nuseWaybillUpload(composableOptions)`, context)
  const paste = (files = [], editable = false) => {
    const event = {
      defaultPrevented: false,
      preventDefault() { this.defaultPrevented = true },
      target: { closest: () => editable ? {} : null },
      clipboardData: { items: files.map(file => ({ kind: 'file', type: file.type, getAsFile: () => file })) },
    }
    return { event, done: listeners.get('paste')(event) }
  }
  state.formRef.value = { validate: async () => Boolean(state.form.waybill_no.trim()), resetFields() {} }
  return { state, paste, requests, messages, revoked, checks, submissions, listeners, unmount: () => unmount() }
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

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('correcting OCR number preserves image mode and other fields, then submits the corrected number', async () => {
  const h = setup()
  await h.paste([picture()]).done
  const preview = h.state.previewUrl.value
  h.state.form.waybill_no = ' 9876 5432 1098 '
  await h.state.onWaybillBlur()
  assert.equal(h.state.mode.value, 'ocr')
  assert.equal(h.state.form.entry_source, 'ocr')
  assert.equal(h.state.form.recipient_name, 'Test')
  assert.equal(h.state.previewUrl.value, preview)
  assert.equal(h.checks.at(-1), '987654321098')
  await h.state.handleSubmit()
  assert.equal(h.submissions[0].waybill_no, '987654321098')
  assert.equal(h.submissions[0].entry_source, 'ocr')
})

test('editing an OCR duplicate clears the warning and allows checking a corrected number', async () => {
  const h = setup(undefined, { check: async no => ({ exists: no === '123456789012', data: { waybill_no: no } }) })
  await h.paste([picture()]).done
  assert.ok(h.state.duplicateInfo.value)
  h.state.form.waybill_no = '987654321098'
  assert.equal(h.state.duplicateInfo.value, null)
  await h.state.onWaybillBlur()
  assert.equal(h.state.duplicateInfo.value, null)
  await h.state.handleSubmit()
  assert.equal(h.submissions.length, 1)
})

test('blurring an unchanged duplicate preserves its existing-shipment link without another request', async () => {
  const h = setup(undefined, { check: async no => ({ exists: true, data: { waybill_no: no, carrier: 'FedEx' } }) })
  await h.paste([picture()]).done
  const duplicate = h.state.duplicateInfo.value
  const count = h.checks.length
  await h.state.onWaybillBlur()
  assert.equal(h.state.duplicateInfo.value, duplicate)
  assert.equal(h.checks.length, count)
  assert.equal(h.state.checkingDuplicate.value, false)
})

test('clearing an OCR number preserves image and recipient, and empty input cannot submit', async () => {
  const h = setup()
  await h.paste([picture()]).done
  h.state.form.waybill_no = ''
  await h.state.onWaybillBlur()
  await h.state.handleSubmit()
  assert.equal(h.state.mode.value, 'ocr')
  assert.equal(h.state.form.recipient_name, 'Test')
  assert.ok(h.state.previewUrl.value)
  assert.equal(h.submissions.length, 0)
})

test('out-of-order duplicate checks cannot overwrite the latest number or its pending state', async () => {
  const first = deferred(), second = deferred()
  const h = setup(undefined, { check: no => no === '111' ? first.promise : second.promise })
  h.state.form.waybill_no = '111'
  const a = h.state.onWaybillBlur()
  h.state.form.waybill_no = '222'
  const b = h.state.onWaybillBlur()
  first.resolve({ exists: true, data: { waybill_no: '111' } })
  await a
  assert.equal(h.state.duplicateInfo.value, null)
  assert.equal(h.state.checkingDuplicate.value, true)
  second.resolve({ exists: false })
  await b
  assert.equal(h.state.checkingDuplicate.value, false)
  assert.equal(h.state.duplicateInfo.value, null)
})

test('reset invalidates pending duplicate results even if the same number is entered again', async () => {
  const pending = deferred()
  const h = setup(undefined, { check: () => pending.promise })
  h.state.form.waybill_no = '111'
  const request = h.state.onWaybillBlur()
  h.state.resetAll()
  h.state.form.waybill_no = '111'
  pending.resolve({ exists: true, data: { waybill_no: '111' } })
  await request
  assert.equal(h.state.duplicateInfo.value, null)
  assert.equal(h.state.checkingDuplicate.value, false)
})

test('submit checks the current number even without blur and blocks duplicates', async () => {
  const h = setup(undefined, { check: async no => ({ exists: true, data: { waybill_no: no } }) })
  h.state.form.waybill_no = ' 123 456 '
  await h.state.handleSubmit()
  assert.equal(h.checks.at(-1), '123456')
  assert.equal(h.submissions.length, 0)
  assert.equal(h.state.duplicateInfo.value.waybill_no, '123456')
  assert.equal(h.state.submitting.value, false)
})

test('failed final duplicate check blocks submission and allows retry', async () => {
  let fail = true
  const h = setup(undefined, { check: async () => { if (fail) throw new Error('offline'); return { exists: false } } })
  h.state.form.waybill_no = '123456789012'
  await h.state.handleSubmit()
  assert.equal(h.submissions.length, 0)
  assert.equal(h.state.submitting.value, false)
  assert.ok(h.messages.some(text => text.includes('查重')))
  fail = false
  await h.state.handleSubmit()
  assert.equal(h.submissions.length, 1)
})

test('double submit while validating or checking creates only one request', async () => {
  const validation = deferred()
  const h = setup()
  h.state.form.waybill_no = '123456789012'
  h.state.formRef.value.validate = () => validation.promise
  const first = h.state.handleSubmit()
  const second = h.state.handleSubmit()
  validation.resolve(true)
  await Promise.all([first, second])
  assert.equal(h.submissions.length, 1)
})

test('blur while final submit check is pending cannot supersede that check', async () => {
  const pending = deferred(), started = deferred()
  const h = setup(undefined, { check: () => { started.resolve(); return pending.promise } })
  h.state.form.waybill_no = '123456789012'
  const submit = h.state.handleSubmit()
  await started.promise
  await h.state.onWaybillBlur()
  assert.equal(h.checks.length, 1)
  pending.resolve({ exists: false })
  await submit
  assert.equal(h.submissions.length, 1)
})

test('inspection submit adapter receives corrected OCR number and retains prefilled fields', async () => {
  let submitted, success
  const h = setup(async () => ({ data: { waybill_no: '', ocr_confidence: 'partial' } }), {
    composableOptions: {
      defaults: { recipient_name: 'Inspection recipient', recipient_country: 'USA' },
      submit: async data => { submitted = { ...data }; return { data: { ...data, shipment_id: 123 } } },
      onSuccess: data => { success = data },
    },
  })
  await h.paste([picture()]).done
  h.state.form.waybill_no = '987654321098'
  await h.state.onWaybillBlur()
  await h.state.handleSubmit()
  assert.equal(h.submissions.length, 0)
  assert.equal(submitted.waybill_no, '987654321098')
  assert.equal(submitted.recipient_name, 'Inspection recipient')
  assert.equal(submitted.recipient_country, 'USA')
  assert.equal(submitted.entry_source, 'ocr')
  assert.equal(success.shipment_id, 123)
})

test('server uniqueness conflict still shows duplicate information and can be corrected', async () => {
  const h = setup(undefined, { submit: async data => {
    throw { response: { status: 409, data: { detail: { data: { waybill_no: data.waybill_no } } } } }
  } })
  h.state.form.waybill_no = '123456789012'
  await h.state.handleSubmit()
  assert.equal(h.state.duplicateInfo.value.waybill_no, '123456789012')
  assert.equal(h.state.submitting.value, false)
  h.state.form.waybill_no = '987654321098'
  assert.equal(h.state.duplicateInfo.value, null)
})
