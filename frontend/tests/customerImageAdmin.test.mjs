import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  createCustomerImageAdminState,
  createProductCoverController,
  createEmptyProductDraft,
  customerImageAdminCapabilities,
  validateInviteDraft,
  validateProductForPublish,
  moveReferenceIds,
  nextReferencePosition,
} from '../src/views/customer-image/admin/composables/useCustomerImageAdmin.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

test('invite validation requires one scoped customer explicit future expiry positive quota and a product', () => {
  const now = new Date('2026-08-09T08:00:00.000Z')
  const valid = {
    customer_id: 'OKKI-1', product_ids: [7],
    expires_at: '2026-08-10T08:00:00.000Z', quota_total: 4,
  }
  assert.equal(validateInviteDraft(valid, now), '')
  assert.match(validateInviteDraft({ ...valid, customer_id: '' }, now), /客户/)
  assert.match(validateInviteDraft({ ...valid, expires_at: '' }, now), /失效时间/)
  assert.match(validateInviteDraft({ ...valid, expires_at: now.toISOString() }, now), /未来/)
  assert.match(validateInviteDraft({ ...valid, quota_total: 0 }, now), /额度/)
  assert.match(validateInviteDraft({ ...valid, product_ids: [] }, now), /产品/)
})

test('reference controls append after the last stable position and reorder two or more assets', () => {
  const references = [
    { id: 11, role: 'reference', position: 0 },
    { id: 12, role: 'reference', position: 1 },
    { id: 13, role: 'reference', position: 2 },
  ]
  assert.equal(nextReferencePosition(references), 3)
  assert.deepEqual(moveReferenceIds(references, 1, -1), [12, 11, 13])
  assert.deepEqual(moveReferenceIds(references, 0, -1), [11, 12, 13])
  assert.deepEqual(moveReferenceIds(references, 2, 1), [11, 12, 13])
})

test('created plaintext invite link is copyable once and closing removes it from state', async () => {
  const calls = []
  const copied = []
  const api = {
    createInvite: async payload => {
      calls.push(payload)
      return { data: { invite: { id: 19 }, invite_url: 'https://example.test/create/secret' } }
    },
    listInvites: async () => ({ data: { items: [], total: 0 } }),
  }
  const state = createCustomerImageAdminState({
    api,
    clipboard: { writeText: async value => copied.push(value) },
    now: () => new Date('2026-08-09T08:00:00.000Z'),
  })
  const draft = {
    customer_id: 'OKKI-1', product_ids: [7],
    expires_at: '2026-08-10T08:00:00.000Z', quota_total: 4,
  }

  await state.submitInvite(draft)
  assert.equal(state.oneTimeInviteUrl.value, 'https://example.test/create/secret')
  assert.deepEqual(calls, [draft])
  await state.copyOneTimeInviteUrl()
  assert.deepEqual(copied, ['https://example.test/create/secret'])
  state.clearOneTimeInviteUrl()
  assert.equal(state.oneTimeInviteUrl.value, '')
})

test('a successful invite remains successful when the independent list refresh fails', async () => {
  let refreshConfig
  const state = createCustomerImageAdminState({
    api: {
      createInvite: async () => ({ data: { invite: { id: 20 }, invite_url: 'https://example.test/create/keep-me' } }),
      listInvites: async (_params, config) => { refreshConfig = config; throw new Error('refresh unavailable') },
    },
    now: () => new Date('2026-08-09T08:00:00.000Z'),
  })
  await state.submitInvite({
    customer_id: 'C1', product_ids: [1], quota_total: 1,
    expires_at: '2026-08-10T08:00:00.000Z',
  })
  assert.equal(state.oneTimeInviteUrl.value, 'https://example.test/create/keep-me')
  assert.deepEqual(refreshConfig, { suppressToast: true })
})

test('admin state uses backend pagination scoped customer search and revoke contracts', async () => {
  const calls = []
  const api = {
    searchCustomers: async params => { calls.push(['customers', params]); return { data: [{ id: 'C1' }] } },
    listProducts: async () => ({ data: [{ id: 3, name: 'Box' }] }),
    listInvites: async params => ({ data: { items: [{ id: 8 }], total: 31, page: params.page, page_size: params.page_size } }),
    listGenerations: async params => ({ data: { items: [{ id: 9 }], total: 22, page: params.page, page_size: params.page_size } }),
    revokeInvite: async id => { calls.push(['revoke', id]); return { data: { id, revoked_at: '2026-08-09' } } },
  }
  const state = createCustomerImageAdminState({ api })

  await state.searchScopedCustomers('Acme')
  await state.loadProducts()
  await state.loadInvites(2, 10)
  await state.loadGenerations(3, 5)
  await state.revokeInvite(8)

  assert.deepEqual(calls, [['customers', { search: 'Acme' }], ['revoke', 8]])
  assert.deepEqual(state.customers.value, [{ id: 'C1' }])
  assert.equal(state.invitePage.value, 2)
  assert.equal(state.inviteTotal.value, 31)
  assert.equal(state.generationPage.value, 3)
  assert.equal(state.generationTotal.value, 22)
  assert.equal(state.invites.value[0].revoked_at, '2026-08-09')
})

test('publish validation covers stable assets prompt fields and option defaults', () => {
  const draft = createEmptyProductDraft()
  draft.name = 'Flip top box'
  draft.category = 'Box'
  draft.fixed_prompt = 'Apply the customer logo.'
  draft.output_prompt = 'Photorealistic product render.'
  draft.options.push({
    key: 'view', label: '角度', control_type: 'single_choice', required: true,
    default_value: 'front', sort: 0,
    values: [{ value: 'front', label: '正面', prompt_fragment: 'front view', sort: 0, is_active: true }],
  })
  assert.match(validateProductForPublish(draft, []), /封面/)
  assert.match(validateProductForPublish(draft, [{ role: 'cover' }]), /参考图/)
  assert.equal(validateProductForPublish(draft, [{ role: 'cover' }, { role: 'reference' }]), '')
  draft.options[0].default_value = ''
  assert.match(validateProductForPublish(draft, [{ role: 'cover' }, { role: 'reference' }]), /默认值/)
})

test('product save sends the exact nested upsert contract with visual order as sort', async () => {
  let captured
  const api = {
    updateProduct: async (id, payload) => {
      captured = { id, payload }
      return { data: { id, config_version: 3, is_published: false, ...payload } }
    },
  }
  const state = createCustomerImageAdminState({ api })
  const draft = {
    id: 4, config_version: 2, is_published: false,
    name: 'Box', category: 'Packaging', description: '',
    fixed_prompt: 'Use logo', output_prompt: 'Studio render', sort: 8,
    options: [{
      id: 71, key: 'finish', label: '表面', control_type: 'color', required: true,
      default_value: 'gold', sort: 99,
      values: [{
        id: 99, value: 'gold', label: '金色', prompt_fragment: 'gold finish',
        color_hex: '#B78B3E', pantone_code: '871 C', sort: 42, is_active: true,
      }],
    }],
  }

  await state.saveProduct(draft)
  assert.equal(captured.id, 4)
  assert.equal(captured.payload.description, null)
  assert.equal(captured.payload.options[0].sort, 0)
  assert.equal(captured.payload.options[0].values[0].sort, 0)
  assert.equal(captured.payload.options[0].values[0].color_hex, '#B78B3E')
  assert.equal('id' in captured.payload.options[0], false)
  assert.equal('id' in captured.payload.options[0].values[0], false)
  assert.equal(state.products.value[0].config_version, 3)
})

test('permission capabilities keep product prompts and mutations admin-only', () => {
  const withPermissions = permissions => customerImageAdminCapabilities(permission => permissions.includes(permission))
  assert.deepEqual(withPermissions(['customer_image:read']), { canAdmin: false, canRead: true, canWrite: false })
  assert.deepEqual(withPermissions(['customer_image:write']), { canAdmin: false, canRead: false, canWrite: true })
  assert.deepEqual(withPermissions(['customer_image:admin']), { canAdmin: true, canRead: true, canWrite: false })
})

test('safe product cover controller downloads current covers once and revokes replacements', async () => {
  const fetched = []
  const revoked = []
  let sequence = 0
  const covers = createProductCoverController({
    fetchCover: async productId => { fetched.push(productId); return { data: { productId } } },
    urlApi: {
      createObjectURL: () => `blob:cover-${++sequence}`,
      revokeObjectURL: url => revoked.push(url),
    },
  })

  await covers.sync([{ id: 1, cover: { id: 4 } }])
  await covers.sync([{ id: 1, cover: { id: 4 } }])
  assert.deepEqual(fetched, [1])
  assert.equal(covers.urls.value[1], 'blob:cover-1')

  await covers.sync([{ id: 1, cover: { id: 5 } }])
  assert.deepEqual(fetched, [1, 1])
  assert.deepEqual(revoked, ['blob:cover-1'])
  assert.equal(covers.urls.value[1], 'blob:cover-2')

  await covers.sync([{ id: 1, cover: null }])
  assert.deepEqual(fetched, [1, 1])
  assert.deepEqual(revoked, ['blob:cover-1', 'blob:cover-2'])
  assert.equal(covers.urls.value[1], undefined)
  await covers.sync([{ id: 1, cover: { id: 6 } }])
  covers.dispose()
  assert.deepEqual(revoked, ['blob:cover-1', 'blob:cover-2', 'blob:cover-3'])
  assert.deepEqual(covers.urls.value, {})
})

test('internal route and Design Center navigation use any-permission while public create stays hidden', () => {
  const navigation = read('../src/config/navigation.js')
  const router = read('../src/router/index.js')
  const admin = read('../src/views/customer-image/admin/CustomerImageAdmin.vue')
  const editor = read('../src/views/customer-image/admin/ProductTemplateEditor.vue')
  const invite = read('../src/views/customer-image/admin/InviteCreateDialog.vue')

  assert.match(navigation, /path:\s*['"]\/design\/customer-image['"]/)
  assert.match(navigation, /anyPermission:\s*\[\s*['"]customer_image:read['"],\s*['"]customer_image:write['"],\s*['"]customer_image:admin['"]\s*\]/)
  assert.doesNotMatch(navigation, /path:\s*['"]\/create/)
  assert.match(router, /anyPermission:\s*entry\.anyPermission/)
  assert.match(admin, /customerImageAdminCapabilities/)
  assert.match(admin, /v-if="canRead"[^>]*label="生成用量"/)
  assert.match(editor, /v-permission=['"]'customer_image:admin'['"]/) 
  assert.match(invite, /customer_image:write/)
  assert.match(invite, /clearOneTimeInviteUrl/)
  assert.match(invite, /productCoverUrls\[product\.id\]/)
  assert.match(invite, /el-checkbox-group/)
  assert.match(editor, /retireProductReference/)
  assert.match(editor, /reorderProductReferences/)
  assert.match(editor, /:aria-label="`上移选项值/)
  assert.match(editor, /:aria-label="`下移选项值/)
})
