import assert from 'node:assert/strict'
import test from 'node:test'

import { useCustomerImagePortal } from '../src/views/customer-image/composables/useCustomerImagePortal.js'

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
    urlApi: { createObjectURL: () => 'blob:logo', revokeObjectURL() {} },
  })

  await portal.bootstrap()
  assert.equal(portal.selectedProduct.value.config_version, 1)
  await portal.submitGeneration()
  assert.equal(portal.selectedProduct.value.config_version, 2)
  assert.deepEqual(portal.state.selections, { finish: 'linen' })
  assert.equal(portal.state.requestId, null)
  assert.match(portal.state.notice, /已更新/)

  await portal.submitGeneration()
  assert.equal(submissions.length, 2)
  assert.equal(submissions[1].config_version, 2)
  assert.deepEqual(submissions[1].selections, { finish: 'linen' })
  assert.equal(portal.state.generations[0].id, 77)
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

  assert.equal(portal.state.resultAnnouncement, '包装盒效果图已生成')
  assert.deepEqual(scrolled, [71])
  assert.equal(portal.state.previewGenerationId, 71)
})
