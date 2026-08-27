import assert from 'node:assert/strict'
import test from 'node:test'

const state = await import('../src/views/customer-image/state.js').catch(() => ({}))
const assets = await import(
  '../src/views/customer-image/composables/useCustomerImageAssets.js'
).catch(() => ({}))

function required(module, name) {
  assert.equal(typeof module[name], 'function', `missing ${name}`)
  return module[name]
}

const PRODUCTS = [
  {
    id: 9,
    config_version: 3,
    name: '翻盖包装盒',
    category: '包装盒',
    options: [
      {
        key: 'finish', label: '表面工艺', control_type: 'single_choice',
        required: true, default_value: 'matte',
        values: [{ value: 'matte', label: '哑光' }, { value: 'gloss', label: '亮光' }],
      },
      {
        key: 'accent', label: '主色', control_type: 'color',
        required: true, default_value: 'gold',
        values: [{ value: 'gold', label: '暖金', color_hex: '#D4941C' }],
      },
      {
        key: 'foil', label: '烫金', control_type: 'boolean',
        required: true, default_value: 'false',
        values: [{ value: 'true', label: '开启' }, { value: 'false', label: '关闭' }],
      },
    ],
  },
]

test('single visible product opens the editor with typed defaults', () => {
  const emptyPortalState = required(state, 'emptyPortalState')
  const applyBootstrap = required(state, 'applyBootstrap')
  const next = applyBootstrap(emptyPortalState(), {
    context: { quota: { total: 4, used: 1, remaining: 3 }, current_logo: null },
    products: PRODUCTS,
    generations: [],
  })

  assert.equal(next.selectedProductId, 9)
  assert.equal(next.view, 'editor')
  assert.deepEqual(next.selections, { finish: 'matte', accent: 'gold', foil: false })
  assert.equal(next.quota.remaining, 3)
  assert.equal(next.notice, null)
  assert.equal(next.error, null)
})

test('multiple products stay in a searchable catalog and zero products show an actionable empty state', () => {
  const emptyPortalState = required(state, 'emptyPortalState')
  const applyBootstrap = required(state, 'applyBootstrap')
  const multiple = applyBootstrap(emptyPortalState(), {
    context: { quota: { total: 2, used: 0, remaining: 2 } },
    products: [...PRODUCTS, { ...PRODUCTS[0], id: 10, name: '抽屉盒' }],
    generations: [],
  })
  assert.equal(multiple.view, 'catalog')
  assert.equal(multiple.selectedProductId, null)

  const empty = applyBootstrap(emptyPortalState(), {
    context: { quota: { total: 2, used: 0, remaining: 2 } },
    products: [],
    generations: [],
  })
  assert.equal(empty.view, 'empty')
  assert.deepEqual(empty.notice, { key: 'portal.empty.detail', params: {} })
  assert.equal(empty.error, null)
})

test('empty portal messages use one nullable descriptor contract', () => {
  const emptyPortalState = required(state, 'emptyPortalState')
  const empty = emptyPortalState()
  assert.equal(empty.error, null)
  assert.equal(empty.notice, null)
  assert.equal(empty.resultAnnouncement, null)
})

test('required options treat boolean false as complete and gate generation on logo quota and submission', () => {
  const requiredOptionsComplete = required(state, 'requiredOptionsComplete')
  const canGenerate = required(state, 'canGenerate')
  const product = PRODUCTS[0]
  const ready = {
    selectedProductId: 9,
    selections: { finish: 'matte', accent: 'gold', foil: false },
    logo: { id: 21 },
    quota: { remaining: 1 },
    submitting: false,
  }
  assert.equal(requiredOptionsComplete(product, ready.selections), true)
  assert.equal(canGenerate(ready, product), true)
  assert.equal(canGenerate({ ...ready, logo: null }, product), false)
  assert.equal(canGenerate({ ...ready, quota: { remaining: 0 } }, product), false)
  assert.equal(canGenerate({ ...ready, submitting: true }, product), false)
  assert.equal(requiredOptionsComplete(product, { ...ready.selections, accent: '' }), false)
})

test('idempotency key remains stable across uncertain failure and resets when inputs change', () => {
  const emptyPortalState = required(state, 'emptyPortalState')
  const ensureRequestId = required(state, 'ensureRequestId')
  const applySubmitFailure = required(state, 'applySubmitFailure')
  const markInputsChanged = required(state, 'markInputsChanged')
  const started = ensureRequestId({ ...emptyPortalState(), submitting: true }, () => 'request-1')
  const repeated = ensureRequestId(started, () => 'request-2')
  const message = { key: 'errors.generationFailed', params: {} }
  const failed = applySubmitFailure(repeated, message)

  assert.equal(repeated.requestId, 'request-1')
  assert.equal(failed.requestId, 'request-1')
  assert.equal(failed.submitting, false)
  assert.equal(failed.notice, null)
  assert.equal(markInputsChanged(failed).requestId, null)
  assert.equal(markInputsChanged(failed).error, null)
})

test('failed submission preserves logo selections requirement and customer-safe error', () => {
  const applySubmitFailure = required(state, 'applySubmitFailure')
  const ready = {
    selections: { finish: 'matte', foil: false },
    logo: { id: 21 },
    requirement: '保持包装结构',
    submitting: true,
    requestId: 'request-1',
  }
  const message = { key: 'errors.generationFailed', params: {} }
  const failed = applySubmitFailure(ready, message)
  assert.deepEqual(failed.selections, ready.selections)
  assert.equal(failed.logo.id, 21)
  assert.equal(failed.requirement, ready.requirement)
  assert.deepEqual(failed.error, message)
})

test('status copy and generation merging keep active work recoverable and newest first', () => {
  const generationStatusMessage = required(state, 'generationStatusMessage')
  const mergeGeneration = required(state, 'mergeGeneration')
  const hasActiveGenerations = required(state, 'hasActiveGenerations')
  assert.deepEqual(generationStatusMessage('queued'), { key: 'generation.queued.detail', params: {} })
  assert.deepEqual(generationStatusMessage('running'), { key: 'generation.running.detail', params: {} })
  assert.deepEqual(generationStatusMessage('succeeded'), { key: 'generation.succeeded.detail', params: {} })
  assert.deepEqual(generationStatusMessage('failed'), { key: 'generation.failed.detail', params: {} })
  assert.deepEqual(generationStatusMessage('other'), { key: 'generation.processing.detail', params: {} })

  const merged = mergeGeneration(
    [{ id: 1, status: 'queued', created_at: '2026-08-09T01:00:00Z' }],
    { id: 2, status: 'running', created_at: '2026-08-09T02:00:00Z' },
  )
  assert.deepEqual(merged.map(item => item.id), [2, 1])
  assert.equal(hasActiveGenerations(merged), true)
})

test('object URL registry revokes replacements and every remaining URL on cleanup', () => {
  const createObjectUrlRegistry = required(assets, 'createObjectUrlRegistry')
  const revoked = []
  let sequence = 0
  const registry = createObjectUrlRegistry({
    createObjectURL: () => `blob:${++sequence}`,
    revokeObjectURL: url => revoked.push(url),
  })

  assert.equal(registry.replace('logo', {}), 'blob:1')
  assert.equal(registry.replace('logo', {}), 'blob:2')
  registry.replace('result:8', {})
  registry.clear()
  assert.deepEqual(revoked, ['blob:1', 'blob:2', 'blob:3'])
})

test('result asset IDs are parsed only from the public asset URL contract', () => {
  const assetIdFromResultUrl = required(assets, 'assetIdFromResultUrl')
  assert.equal(assetIdFromResultUrl('/api/customer-image/public/assets/81/content'), 81)
  assert.equal(assetIdFromResultUrl('/uploads/private/customer-logo.png'), null)
  assert.equal(assetIdFromResultUrl('https://evil.example/assets/81/content'), null)
})

test('deferred logo and result responses never create object URLs after disposal', async () => {
  const createController = required(assets, 'createCustomerImageAssetController')
  const pending = []
  const created = []
  const controller = createController({
    fetchProductAsset: (productId, id) => new Promise(resolve => pending.push({ id, productId, resolve })),
    fetchInviteAsset: id => new Promise(resolve => pending.push({ id, resolve })),
    urlApi: {
      createObjectURL(blob) { created.push(blob); return `blob:${created.length}` },
      revokeObjectURL() {},
    },
  })

  const logoLoad = controller.loadLogo({ id: 21 })
  const resultLoad = controller.loadGeneration({
    id: 8,
    status: 'succeeded',
    result_url: '/api/customer-image/public/assets/81/content',
  })
  const coverLoad = controller.loadProductCovers([{
    id: 9,
    assets: [{ id: 44, role: 'cover' }],
  }])
  controller.dispose()
  for (const request of pending) request.resolve({ data: { id: request.id } })
  await Promise.all([logoLoad, resultLoad, coverLoad])

  assert.deepEqual(created, [])
  assert.equal(controller.logoUrl.value, '')
  assert.deepEqual({ ...controller.generationUrls }, {})
  assert.deepEqual({ ...controller.coverUrls }, {})
})

test('logo assets download once per id and revoke only on replacement or removal', async () => {
  const createController = required(assets, 'createCustomerImageAssetController')
  const fetched = []
  const revoked = []
  let sequence = 0
  const controller = createController({
    fetchProductAsset: () => assert.fail(),
    fetchInviteAsset: async id => { fetched.push(id); return { data: { id } } },
    urlApi: {
      createObjectURL: () => `blob:${++sequence}`,
      revokeObjectURL: url => revoked.push(url),
    },
  })

  assert.equal(await controller.loadLogo({ id: 21 }), 'blob:1')
  assert.equal(await controller.loadLogo({ id: 21 }), 'blob:1')
  assert.deepEqual(fetched, [21])
  assert.deepEqual(revoked, [])

  assert.equal(await controller.loadLogo({ id: 22 }), 'blob:2')
  assert.deepEqual(fetched, [21, 22])
  assert.deepEqual(revoked, ['blob:1'])

  assert.equal(await controller.loadLogo(null), '')
  assert.deepEqual(fetched, [21, 22])
  assert.deepEqual(revoked, ['blob:1', 'blob:2'])
  assert.equal(await controller.loadLogo(null), '')
  assert.deepEqual(revoked, ['blob:1', 'blob:2'])
})
