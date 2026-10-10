import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'

const source = fs.readFileSync(new URL('../src/composables/useDocumentRemark.js', import.meta.url), 'utf8')
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
async function harness(kind = 'invoice') {
  const props = vue.reactive({ kind, disabled: false, document: {
    id: 1, remark: 'old', edit_version: 'v1', version: 1, status: kind === 'invoice' ? 'synced' : 'active', sync_status: 'synced',
  } })
  const pending = deferred(), calls = [], emitted = [], states = []
  let dispose
  const auth = vue.reactive({ user: { id: 801, roles: [], permissions: ['invoice:write', 'receipt:write'] } })
  const save = (...args) => { calls.push(args); return pending.promise }
  const imports = {
    vue: { ...vue, onUnmounted(fn) { dispose = fn } },
    '@/api/invoice': { updateInvoiceRemark: save },
    '@/api/receipt': { updateReceiptRemark: save },
    '@/utils/feedback': { msgSuccessText() {} },
    '@/stores/auth': { useAuthStore: () => auth },
  }
  const context = vm.createContext({})
  const module = new vm.SourceTextModule(source, { context })
  await module.link(name => {
    const entries = imports[name]
    return new vm.SyntheticModule(Object.keys(entries), function () {
      for (const [key, value] of Object.entries(entries)) this.setExport(key, value)
    }, { context })
  })
  await module.evaluate()
  const scope = vue.effectScope()
  const editor = scope.run(() => module.namespace.useDocumentRemark(props, (...args) => {
    (args[0] === 'updated' ? emitted : states).push(args)
  }))
  return { props, editor, pending, calls, emitted, states, auth, dispose() { dispose(); scope.stop() } }
}

for (const kind of ['invoice', 'receipt']) {
  test(`${kind}: edit/clear saves only remark with captured version, even after refresh`, async () => {
    const h = await harness(kind)
    try {
      assert.equal(h.editor.editable.value, true)
      h.editor.start(); assert.equal(h.editor.draft.value, 'old')
      h.editor.draft.value = ''
      h.props.document.version = 2; h.props.document.edit_version = 'v2'
      const saving = h.editor.save()
      assert.equal(h.calls[0][0], 1)
      assert.deepEqual(JSON.parse(JSON.stringify(h.calls[0][1])), kind === 'invoice'
        ? { remark: '', expected_version: 'v1' } : { remark: '', version: 1 })
      h.pending.resolve({ id: 1, remark: '' }); await saving
      assert.equal(h.editor.editing.value, false)
      assert.equal(h.emitted[0][0], 'updated')
    } finally { h.dispose() }
  })
}
test('failed save retains text and exposes conflict for retry', async () => {
  const h = await harness()
  try {
    h.editor.start(); h.editor.draft.value = 'new'
    const saving = h.editor.save()
    h.pending.reject({ response: { data: { detail: 'Please refresh' } } }); await saving
    assert.equal(h.editor.editing.value, true); assert.equal(h.editor.draft.value, 'new')
    assert.equal(h.editor.error.value, 'Please refresh'); assert.equal(h.emitted.length, 0)
  } finally { h.dispose() }
})
test('double click does not send duplicate request', async () => {
  const h = await harness()
  try {
    h.editor.start(); const saving = h.editor.save(); await h.editor.save()
    assert.equal(h.calls.length, 1); h.pending.resolve({ id: 1 }); await saving
  } finally { h.dispose() }
})
for (const action of ['switch', 'dispose', 'revoke permission', 'switch account']) {
  test(`response after ${action} cannot overwrite the next document`, async () => {
    const h = await harness()
    try {
      h.editor.start(); const saving = h.editor.save()
      if (action === 'switch') h.props.document = { ...h.props.document, id: 2 }
      else if (action === 'revoke permission') h.auth.user.permissions = []
      else if (action === 'switch account') h.auth.user.id = 802
      else h.dispose()
      h.pending.resolve({ id: 1, remark: 'late' }); await saving
      assert.equal(h.emitted.length, 0); assert.equal(h.editor.editing.value, false)
    } finally { h.dispose() }
  })
}
test('cancel discards edits without sending a request', async () => {
  const h = await harness()
  try {
    h.editor.start(); h.editor.draft.value = 'unsaved'; h.editor.cancel(); h.editor.start()
    assert.equal(h.editor.draft.value, 'old'); assert.equal(h.calls.length, 0)
  } finally { h.dispose() }
})
test('syncing receipt cannot open or submit remark edits', async () => {
  const h = await harness('receipt')
  try {
    h.props.document.sync_status = 'syncing'; h.editor.start(); await h.editor.save()
    assert.equal(h.editor.editing.value, false); assert.equal(h.calls.length, 0)
  } finally { h.dispose() }
})

test('receipt editor reports editing and saving so its order form can block competing writes', async () => {
  const h = await harness('receipt')
  try {
    h.editor.start()
    const saving = h.editor.save()
    assert.deepEqual(h.states.map(args => [...args]), [['editing', true], ['saving', true]])
    h.pending.resolve({ id: 1, version: 2, remark: 'old' }); await saving
    assert.deepEqual(h.states.map(args => [...args]), [
      ['editing', true], ['saving', true], ['editing', false], ['saving', false],
    ])
  } finally { h.dispose() }
})
