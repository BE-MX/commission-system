import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  createCustomerImageAdminState,
  createAssetBlobController,
  createProductCoverController,
  createEmptyProductDraft,
  customerImageAdminCapabilities,
  inviteSubmissionErrorMessage,
  validateInviteDraft,
  validateProductForPublish,
  moveReferenceIds,
} from '../src/views/customer-image/admin/composables/useCustomerImageAdmin.js'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')

function deferred() {
  let resolve
  let reject
  const promise = new Promise((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

test('asset blob epochs ignore inverse late loads and disposal without creating URLs', async () => {
  const requests = new Map()
  const created = []
  const revoked = []
  const controller = createAssetBlobController({
    fetchBlob: item => {
      const request = deferred()
      requests.set(item.id, request)
      return request.promise
    },
    urlApi: {
      createObjectURL: blob => { const url = `blob:${blob}`; created.push(url); return url },
      revokeObjectURL: url => revoked.push(url),
    },
  })

  const oldLoad = controller.load([{ id: 1 }])
  const newLoad = controller.load([{ id: 2 }])
  requests.get(2).resolve({ data: 'new' })
  await newLoad
  requests.get(1).resolve({ data: 'old' })
  await oldLoad
  assert.deepEqual(created, ['blob:new'])
  assert.deepEqual(controller.urls.value, { 2: 'blob:new' })

  const disposedLoad = controller.load([{ id: 3 }])
  controller.dispose()
  requests.get(3).resolve({ data: 'disposed' })
  await disposedLoad
  assert.deepEqual(created, ['blob:new'])
  assert.deepEqual(revoked, ['blob:new'])
})

test('admin list request versions keep only the latest result per independent resource', async () => {
  const pending = {
    customers: [deferred(), deferred()], products: [deferred(), deferred()],
    invites: [deferred(), deferred()], generations: [deferred(), deferred()],
  }
  const shifts = Object.fromEntries(Object.entries(pending).map(([key, values]) => [key, [...values]]))
  const state = createCustomerImageAdminState({
    api: {
      searchCustomers: () => shifts.customers.shift().promise,
      listProducts: () => shifts.products.shift().promise,
      listInvites: () => shifts.invites.shift().promise,
      listGenerations: () => shifts.generations.shift().promise,
      getProductCoverBlob: async () => ({ data: 'cover' }),
    },
  })
  const calls = [
    state.searchScopedCustomers('old'), state.searchScopedCustomers('new'),
    state.loadProducts(), state.loadProducts(),
    state.loadInvites(1, 20), state.loadInvites(2, 10),
    state.loadGenerations(1, 20), state.loadGenerations(3, 5),
  ]
  pending.customers[1].resolve({ data: [{ id: 'new' }] })
  pending.products[1].resolve({ data: [{ id: 2, name: 'new', cover: null }] })
  pending.invites[1].resolve({ data: { items: [{ id: 2 }], page: 2, page_size: 10, total: 1 } })
  pending.generations[1].resolve({ data: { items: [{ id: 3 }], page: 3, page_size: 5, total: 1 } })
  pending.customers[0].resolve({ data: [{ id: 'old' }] })
  pending.products[0].resolve({ data: [{ id: 1, name: 'old', cover: null }] })
  pending.invites[0].resolve({ data: { items: [{ id: 1 }], page: 1, page_size: 20, total: 1 } })
  pending.generations[0].resolve({ data: { items: [{ id: 1 }], page: 1, page_size: 20, total: 1 } })
  await Promise.all(calls)

  assert.deepEqual(state.customers.value, [{ id: 'new' }])
  assert.equal(state.products.value[0].name, 'new')
  assert.equal(state.invites.value[0].id, 2)
  assert.equal(state.invitePage.value, 2)
  assert.equal(state.generations.value[0].id, 3)
  assert.equal(state.generationPage.value, 3)
})

test('copy failure or unavailable clipboard keeps the one-time URL for manual copying', async () => {
  for (const clipboard of [undefined, { writeText: async () => { throw new Error('denied') } }]) {
    const state = createCustomerImageAdminState({ clipboard, api: { getProductCoverBlob: async () => ({}) } })
    state.oneTimeInviteUrl.value = 'https://example.test/create/keep'
    assert.equal(await state.copyOneTimeInviteUrl(), false)
    assert.equal(state.oneTimeInviteUrl.value, 'https://example.test/create/keep')
  }
  const invite = read('../src/views/customer-image/admin/InviteCreateDialog.vue')
  assert.match(invite, /自动复制失败，请手动选择上方链接复制/)
})

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

test('invite submission errors are actionable and hide internal HTTP details', () => {
  const httpError = (status, detail) => ({ response: { status, data: { detail } } })
  assert.equal(
    inviteSubmissionErrorMessage(httpError(404, 'customer not found')),
    '所选客户已失效，请重新搜索并选择客户',
  )
  assert.equal(
    inviteSubmissionErrorMessage(httpError(404, 'customer owner not found')),
    '该客户缺少当前负责人，请联系管理员补全客户归属后重试',
  )
  assert.equal(
    inviteSubmissionErrorMessage(httpError(404, 'published product not found')),
    '所选产品已下架或不可用，请刷新页面后重新选择产品',
  )
  assert.equal(
    inviteSubmissionErrorMessage(httpError(404, 'Not Found')),
    '系统接口未加载，请刷新页面；若仍失败，请联系管理员重启后端服务',
  )
  assert.equal(
    inviteSubmissionErrorMessage(httpError(404, 'database row missing: secret-path')),
    '客户或产品已失效，请刷新页面后重新选择',
  )
  assert.equal(
    inviteSubmissionErrorMessage(httpError(409, 'duplicate token_hash: secret-token')),
    '客户或产品状态已变化，请刷新页面后重试',
  )
  assert.equal(
    inviteSubmissionErrorMessage(httpError(503, 'provider password=secret')),
    '服务暂时不可用，请稍后重试',
  )
  assert.equal(
    inviteSubmissionErrorMessage(httpError(500, 'Traceback: C:\\private\\app.py')),
    '邀请链接生成失败，请稍后重试；若仍失败，请联系管理员',
  )
  assert.equal(
    inviteSubmissionErrorMessage(new Error('Network Error')),
    '网络连接失败，请检查网络后重试',
  )

  const dialog = read('../src/views/customer-image/admin/InviteCreateDialog.vue')
  assert.match(dialog, /ElMessage\.warning\(inviteSubmissionErrorMessage\(error\)\)/)
  assert.doesNotMatch(dialog, /if \(!error\?\.response\)/)
})

test('reference controls reorder two or more assets without client-side append positions', () => {
  const references = [
    { id: 11, role: 'reference', position: 0 },
    { id: 12, role: 'reference', position: 1 },
    { id: 13, role: 'reference', position: 2 },
  ]
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
