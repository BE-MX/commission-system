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
  assert.match(empty.notice, /联系.*业务/)
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
  const failed = applySubmitFailure(repeated, '服务暂不可用')

  assert.equal(repeated.requestId, 'request-1')
  assert.equal(failed.requestId, 'request-1')
  assert.equal(failed.submitting, false)
  assert.equal(markInputsChanged(failed).requestId, null)
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
  const failed = applySubmitFailure(ready, '生图服务暂时不可用，本次设置已保留，请稍后重试')
  assert.deepEqual(failed.selections, ready.selections)
  assert.equal(failed.logo.id, 21)
  assert.equal(failed.requirement, ready.requirement)
  assert.match(failed.error, /设置已保留/)
})

test('status copy and generation merging keep active work recoverable and newest first', () => {
  const generationStatusText = required(state, 'generationStatusText')
  const mergeGeneration = required(state, 'mergeGeneration')
  const hasActiveGenerations = required(state, 'hasActiveGenerations')
  assert.match(generationStatusText('queued'), /可以关闭页面/)
  assert.match(generationStatusText('running'), /几十秒到数分钟/)
  assert.match(generationStatusText('succeeded'), /已完成/)
  assert.match(generationStatusText('failed'), /重试/)

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
