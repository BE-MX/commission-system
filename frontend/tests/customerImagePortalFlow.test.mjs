import assert from 'node:assert/strict'
import test from 'node:test'

import { useCustomerImagePortal } from '../src/views/customer-image/composables/useCustomerImagePortal.js'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

function lifecycle() {
  return { onMounted() {}, onBeforeUnmount() {} }
}

function quietPolling() {
  return { schedule: () => 1, cancelSchedule() {} }
}

function product(version, defaultValue) {
  return {
    id: 9,
    config_version: version,
    name: '包装盒',
    options: [{
      key: 'finish',
      label: '表面工艺',
      control_type: 'single_choice',
      required: true,
      default_value: defaultValue,
      values: [{ value: defaultValue, label: defaultValue }],
    }],
    assets: [],
  }
}

function baseApi(overrides = {}) {
  return {
    getContext: async () => ({ data: { quota: { total: 2, used: 0, remaining: 2 }, current_logo: { id: 21 } } }),
    listProducts: async () => ({ data: [product(1, 'matte')] }),
    listGenerations: async () => ({ data: [] }),
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => ({ data: { id: 22 } }),
    createGeneration: async () => assert.fail(),
    ...overrides,
  }
}

test('settings conflict refreshes product defaults and the next explicit submit uses the new version', async () => {
  let catalogVersion = 1
  const submissions = []
  const api = {
    getContext: async () => ({ data: {
      quota: { total: 4, used: 0, remaining: 4 },
      current_logo: { id: 21 },
    } }),
    listProducts: async () => ({ data: [
      catalogVersion === 1 ? product(1, 'matte') : product(2, 'linen'),
    ] }),
    listGenerations: async () => ({ data: [] }),
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => assert.fail('unexpected logo upload'),
    async createGeneration(payload) {
      submissions.push(payload)
      if (submissions.length === 1) {
        catalogVersion = 2
        throw { response: { status: 409, data: { detail: 'Product settings changed. Please choose again.' } } }
      }
      return { data: { id: 77, product_id: 9, product_name: '包装盒', status: 'queued', created_at: '2026-08-09T01:00:00Z' } }
    },
  }
  const portal = useCustomerImagePortal({
    api,
    lifecycle: { onMounted() {}, onBeforeUnmount() {} },
    ...quietPolling(),
    urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL() {} },
  })

  await portal.bootstrap()
  assert.equal(portal.selectedProduct.value.config_version, 1)
  await portal.submitGeneration()
  assert.equal(portal.selectedProduct.value.config_version, 2)
  assert.deepEqual(portal.state.selections, { finish: 'linen' })
  assert.equal(portal.state.requestId, null)
  assert.deepEqual(portal.state.notice, { key: 'settings.updated', params: {} })

  await portal.submitGeneration()
  assert.equal(submissions.length, 2)
  assert.equal(submissions[1].config_version, 2)
  assert.deepEqual(submissions[1].selections, { finish: 'linen' })
  assert.equal(portal.state.generations[0].id, 77)
})

test('deferred submit locks every mutation and keeps one stable request payload', async () => {
  const post = deferred()
  const submissions = []
  const api = {
    getContext: async () => ({ data: { quota: { total: 4, used: 0, remaining: 4 }, current_logo: { id: 21 } } }),
    listProducts: async () => ({ data: [product(1, 'matte'), { ...product(1, 'matte'), id: 10 }] }),
    listGenerations: async () => ({ data: [] }),
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => assert.fail('logo mutation must be locked'),
    createGeneration: payload => { submissions.push(structuredClone(payload)); return post.promise },
  }
  const portal = useCustomerImagePortal({ api, lifecycle: lifecycle(), ...quietPolling(), urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL() {} } })
  await portal.bootstrap()
  portal.chooseProduct(portal.state.products[0])
  portal.updateRequirement('keep me')
  const submitting = portal.submitGeneration()
  const requestId = portal.state.requestId

  portal.updateSelection('finish', 'changed')
  portal.updateRequirement('changed')
  portal.chooseProduct(portal.state.products[1])
  portal.backToCatalog()
  await portal.replaceLogo({ name: 'other.png' })
  await portal.submitGeneration()

  assert.equal(submissions.length, 1)
  assert.equal(submissions[0].request_id, requestId)
  assert.deepEqual(Object.keys(submissions[0]).sort(), [
    'config_version', 'product_id', 'request_id', 'requirement', 'selections',
  ])
  assert.deepEqual(submissions[0].selections, { finish: 'matte' })
  assert.equal(submissions[0].requirement, 'keep me')
  assert.equal(portal.state.selectedProductId, 9)
  assert.deepEqual(portal.state.selections, { finish: 'matte' })
  assert.equal(portal.state.requirement, 'keep me')

  post.resolve({ data: { id: 80, product_id: 9, product_name: '包装盒', status: 'queued', created_at: '2026-08-09T02:00:00Z' } })
  await submitting
})

test('a stale bootstrap list also preserves a locally accepted queued generation', async () => {
  let listCalls = 0
  const staleBootstrap = deferred()
  const api = {
    getContext: async () => ({ data: { quota: { total: 2, used: 0, remaining: 2 }, current_logo: { id: 21 } } }),
    listProducts: async () => ({ data: [product(1, 'matte')] }),
    listGenerations: async () => { listCalls += 1; return listCalls === 1 ? { data: [] } : staleBootstrap.promise },
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => assert.fail(),
    createGeneration: async () => ({ data: { id: 83, product_id: 9, product_name: '包装盒', status: 'queued', created_at: '2026-08-09T02:00:00Z' } }),
  }
  const portal = useCustomerImagePortal({ api, lifecycle: lifecycle(), ...quietPolling(), urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL() {} } })
  await portal.bootstrap()
  await portal.submitGeneration()
  const bootstrapping = portal.bootstrap()
  staleBootstrap.resolve({ data: [] })
  await bootstrapping
  assert.equal(portal.state.generations[0].id, 83)
})

test('accepted generation remains successful when the independent context refresh fails', async () => {
  let contextCalls = 0
  let createCalls = 0
  const api = {
    getContext: async () => {
      contextCalls += 1
      if (contextCalls > 1) throw { response: { status: 503 } }
      return { data: { quota: { total: 2, used: 0, remaining: 2 }, current_logo: { id: 21 } } }
    },
    listProducts: async () => ({ data: [product(1, 'matte')] }),
    listGenerations: async () => ({ data: [] }),
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => assert.fail(),
    createGeneration: async () => {
      createCalls += 1
      return { data: { id: 81, product_id: 9, product_name: '包装盒', status: 'queued', created_at: '2026-08-09T02:00:00Z' } }
    },
  }
  const portal = useCustomerImagePortal({ api, lifecycle: lifecycle(), ...quietPolling(), urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL() {} } })
  await portal.bootstrap()
  await portal.submitGeneration()
  assert.equal(createCalls, 1)
  assert.equal(portal.state.generations[0].id, 81)
  assert.equal(portal.state.error, null)
  assert.equal(portal.state.requestId, null)
  assert.deepEqual(portal.state.notice, { key: 'generation.queued.detail', params: {} })
})

test('an older generation list cannot overwrite a newly accepted queued generation', async () => {
  const oldList = deferred()
  let listCalls = 0
  const api = {
    getContext: async () => ({ data: { quota: { total: 2, used: 0, remaining: 2 }, current_logo: { id: 21 } } }),
    listProducts: async () => ({ data: [product(1, 'matte')] }),
    listGenerations: async () => { listCalls += 1; return listCalls === 1 ? { data: [] } : oldList.promise },
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => assert.fail(),
    createGeneration: async () => ({ data: { id: 82, product_id: 9, product_name: '包装盒', status: 'queued', created_at: '2026-08-09T02:00:00Z' } }),
  }
  const portal = useCustomerImagePortal({ api, lifecycle: lifecycle(), ...quietPolling(), urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL() {} } })
  await portal.bootstrap()
  const polling = portal.pollGenerations()
  await portal.submitGeneration()
  oldList.resolve({ data: [] })
  await polling
  assert.equal(portal.state.generations[0].id, 82)
  assert.equal(portal.state.generations[0].status, 'queued')
})

test('public 401 invalidates invite state token polling and loaded assets in one path', async () => {
  let listCalls = 0
  let cleared = 0
  const revoked = []
  const api = {
    getContext: async () => ({ data: { quota: { total: 2, used: 0, remaining: 2 }, current_logo: { id: 21 } } }),
    listProducts: async () => ({ data: [product(1, 'matte')] }),
    listGenerations: async () => { listCalls += 1; if (listCalls > 1) throw { response: { status: 401 } }; return { data: [] } },
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => assert.fail(),
    createGeneration: async () => assert.fail(),
  }
  const portal = useCustomerImagePortal({
    api,
    lifecycle: lifecycle(),
    ...quietPolling(),
    clearInvite: () => { cleared += 1 },
    urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL: url => revoked.push(url) },
  })
  await portal.bootstrap()
  await portal.pollGenerations()
  assert.equal(cleared, 1)
  assert.equal(portal.state.view, 'invalid')
  assert.equal(portal.state.context, null)
  assert.deepEqual(portal.state.products, [])
  assert.deepEqual(portal.state.selections, {})
  assert.equal(portal.state.logo, null)
  assert.deepEqual(portal.state.notice, { key: 'errors.invalidLink', params: {} })
  assert.equal(portal.state.error, null)
  assert.equal(portal.state.resultAnnouncement, null)
  assert.deepEqual(revoked, ['blob:logo'])
})

test('quota or logo conflict refreshes both values and clears stale logo preview', async () => {
  let contextCalls = 0
  const revoked = []
  const api = {
    getContext: async () => {
      contextCalls += 1
      return { data: contextCalls === 1
        ? { quota: { total: 1, used: 0, remaining: 1 }, current_logo: { id: 21 } }
        : { quota: { total: 1, used: 1, remaining: 0 }, current_logo: null } }
    },
    listProducts: async () => ({ data: [product(1, 'matte')] }),
    listGenerations: async () => ({ data: [] }),
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => assert.fail(),
    createGeneration: async () => { throw { response: { status: 409, data: { detail: 'quota exhausted' } } } },
  }
  const portal = useCustomerImagePortal({ api, lifecycle: lifecycle(), ...quietPolling(), urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL: url => revoked.push(url) } })
  await portal.bootstrap()
  await portal.submitGeneration()
  assert.equal(portal.state.quota.remaining, 0)
  assert.equal(portal.state.logo, null)
  assert.equal(portal.assets.logoUrl.value, '')
  assert.deepEqual(revoked, ['blob:logo'])
  assert.deepEqual(portal.state.error, { key: 'errors.quotaExhausted', params: {} })
})

test('upload blob and settings-refresh 401s all use the same invite invalidation', async (t) => {
  await t.test('upload', async () => {
    let cleared = 0
    const portal = useCustomerImagePortal({
      api: baseApi({ uploadLogo: async () => { throw { response: { status: 401 } } } }),
      lifecycle: lifecycle(), ...quietPolling(), clearInvite: () => { cleared += 1 },
      urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL() {} },
    })
    await portal.bootstrap()
    await portal.replaceLogo({ name: 'logo.png' })
    assert.equal(cleared, 1)
    assert.equal(portal.state.view, 'invalid')
  })

  await t.test('result blob', async () => {
    let assetCalls = 0
    let cleared = 0
    const portal = useCustomerImagePortal({
      api: baseApi({ getAssetBlob: async () => {
        assetCalls += 1
        if (assetCalls > 1) throw { response: { status: 401 } }
        return { data: {} }
      } }),
      lifecycle: lifecycle(), ...quietPolling(), clearInvite: () => { cleared += 1 },
      urlApi: { createObjectURL: () => 'blob:asset', revokeObjectURL() {} },
    })
    await portal.bootstrap()
    await portal.selectGeneration({ id: 90, status: 'succeeded', result_url: '/api/customer-image/public/assets/90/content' })
    assert.equal(cleared, 1)
    assert.equal(portal.state.view, 'invalid')
  })

  await t.test('settings refresh', async () => {
    let productCalls = 0
    let cleared = 0
    const portal = useCustomerImagePortal({
      api: baseApi({
        listProducts: async () => {
          productCalls += 1
          if (productCalls > 1) throw { response: { status: 401 } }
          return { data: [product(1, 'matte')] }
        },
        createGeneration: async () => { throw { response: { status: 409, data: { detail: 'Product settings changed.' } } } },
      }),
      lifecycle: lifecycle(), ...quietPolling(), clearInvite: () => { cleared += 1 },
      urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL() {} },
    })
    await portal.bootstrap()
    await portal.submitGeneration()
    assert.equal(cleared, 1)
    assert.equal(portal.state.view, 'invalid')
  })
})

test('active generation completion announces politely and scrolls the result without focus', async () => {
  let generations = [{ id: 71, product_id: 9, product_name: '包装盒', status: 'running', created_at: '2026-08-09T01:00:00Z' }]
  const scrolled = []
  const api = {
    getContext: async () => ({ data: { quota: { total: 4, used: 1, remaining: 3 }, current_logo: { id: 21 } } }),
    listProducts: async () => ({ data: [product(2, 'linen')] }),
    listGenerations: async () => ({ data: generations }),
    getProductAssetBlob: async () => ({ data: {} }),
    getAssetBlob: async () => ({ data: {} }),
    uploadLogo: async () => assert.fail(),
    createGeneration: async () => assert.fail(),
  }
  const portal = useCustomerImagePortal({
    api,
    lifecycle: { onMounted() {}, onBeforeUnmount() {} },
    ...quietPolling(),
    urlApi: { createObjectURL: () => 'blob:result', revokeObjectURL() {} },
    schedule: () => 1,
    scrollResultIntoView: id => scrolled.push(id),
  })
  await portal.bootstrap()
  generations = [{
    ...generations[0],
    status: 'succeeded',
    result_url: '/api/customer-image/public/assets/81/content',
  }]
  await portal.pollGenerations()

  assert.deepEqual(portal.state.resultAnnouncement, {
    key: 'generation.completed.announcement',
    params: { product: '包装盒' },
  })
  assert.deepEqual(scrolled, [71])
  assert.equal(portal.state.previewGenerationId, 71)
})
