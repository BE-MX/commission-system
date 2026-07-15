import test from 'node:test'
import assert from 'node:assert/strict'
import {
  buildAccessoryEditorState,
  createLatestAccessorySearch,
  deleteAccessoryPriceRow,
  saveAccessoryPriceForm,
  shouldShowAccessoryLocalError,
} from '../src/views/invoice/composables/accessoryPriceConfigState.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

test('latest accessory search alone may update candidates and loading', async () => {
  const first = deferred()
  const second = deferred()
  const requests = [first, second]
  const states = []
  let candidates = [{ sku_id: 'initial' }]
  let loading = false
  const search = createLatestAccessorySearch({
    request: () => requests.shift().promise,
    applyItems: items => { candidates = items },
    applyLoading: value => {
      loading = value
      states.push(value)
    },
  })

  const older = search({ keyword: 'old' })
  const latest = search({ keyword: 'new' })
  first.resolve({ items: [{ sku_id: 'old' }] })
  await older
  assert.deepEqual(candidates, [{ sku_id: 'initial' }])
  assert.equal(loading, true)

  second.resolve({ items: [{ sku_id: 'new' }] })
  await latest
  assert.deepEqual(candidates, [{ sku_id: 'new' }])
  assert.equal(loading, false)
  assert.deepEqual(states, [true, true, false])
})

test('only the latest failed accessory search may clear candidates', async () => {
  const first = deferred()
  const second = deferred()
  let candidates = [{ sku_id: 'initial' }]
  const search = createLatestAccessorySearch({
    request: (() => {
      const requests = [first, second]
      return () => requests.shift().promise
    })(),
    applyItems: items => { candidates = items },
    applyLoading: () => {},
  })

  const older = search({ keyword: 'old' })
  const latest = search({ keyword: 'new' })
  first.reject(new Error('old failed'))
  await assert.rejects(older, /old failed/)
  assert.deepEqual(candidates, [{ sku_id: 'initial' }])
  second.reject(new Error('new failed'))
  await assert.rejects(latest, /new failed/)
  assert.deepEqual(candidates, [])
})

test('invalidating a search session ends loading and blocks its late result from a reopened dialog', async () => {
  const staleRequest = deferred()
  const currentRequest = deferred()
  const requests = [staleRequest, currentRequest]
  let candidates = []
  let loading = false
  const search = createLatestAccessorySearch({
    request: () => requests.shift().promise,
    applyItems: items => { candidates = items },
    applyLoading: value => { loading = value },
  })

  const stale = search({ keyword: 'closed dialog' })
  search.invalidate()
  assert.equal(loading, false)

  candidates = [{ sku_id: 'reopened' }]
  const current = search({ keyword: 'reopened dialog' })
  staleRequest.resolve({ items: [{ sku_id: 'stale' }] })
  await stale
  assert.deepEqual(candidates, [{ sku_id: 'reopened' }])
  assert.equal(loading, true)

  currentRequest.resolve({ items: [{ sku_id: 'current' }] })
  await current
  assert.deepEqual(candidates, [{ sku_id: 'current' }])
  assert.equal(loading, false)
})

test('editing an accessory keeps the record and real OKKI identities in the payload', async () => {
  const state = buildAccessoryEditorState({
    id: 9,
    product_id: 104881553777436,
    sku_id: 104881553777819,
    accessory_name: 'Hair Gripper',
    accessory_model: '魔术贴',
    accessory_color: 'Hair Gripper',
    standard_price: '2.50',
    currency: 'USD',
  })
  assert.equal(state.form.id, 9)
  assert.equal(state.form.product_id, 104881553777436)
  assert.equal(state.form.sku_id, 104881553777819)
  assert.equal(state.candidate.product_id, 104881553777436)
  assert.equal(state.candidate.sku_id, 104881553777819)
  let payload
  await saveAccessoryPriceForm({
    form: state.form,
    save: async value => { payload = value },
    onSuccess: () => {},
  })
  assert.equal(payload.id, 9)
  assert.equal(payload.product_id, 104881553777436)
  assert.equal(payload.sku_id, 104881553777819)
})

test('failed save does not invoke the dialog success callback', async () => {
  let closed = false
  await assert.rejects(
    saveAccessoryPriceForm({
      form: { id: 9, product_id: 1, sku_id: 2, price: 2.5, currency: 'USD' },
      save: async () => { throw new Error('save failed') },
      onSuccess: () => { closed = true },
    }),
    /save failed/,
  )
  assert.equal(closed, false)
})

test('cancelled delete does not call the delete API', async () => {
  let deleteCalls = 0
  const deleted = await deleteAccessoryPriceRow({
    row: { id: 9 },
    confirm: async () => { throw 'cancel' },
    remove: async () => { deleteCalls += 1 },
  })
  assert.equal(deleted, false)
  assert.equal(deleteCalls, 0)
})

test('delete API failures still propagate for request feedback', async () => {
  await assert.rejects(
    deleteAccessoryPriceRow({
      row: { id: 9 },
      confirm: async () => {},
      remove: async () => { throw new Error('delete failed') },
    }),
    /delete failed/,
  )
})

test('Axios failures are left exclusively to the shared interceptor', () => {
  assert.equal(shouldShowAccessoryLocalError({ isAxiosError: true, message: 'Network Error' }), false)
  assert.equal(shouldShowAccessoryLocalError(new Error('local callback failed')), true)
})
