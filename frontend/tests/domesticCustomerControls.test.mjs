import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import { reactive, ref } from 'vue'
import { useListPage } from '../src/composables/useListPage.js'

const source = readFileSync(new URL('../src/views/domestic/composables/useDomesticCustomers.js', import.meta.url), 'utf8')

function createState({ permissions = [], roles = [] } = {}) {
  const requests = []
  const context = {
    reactive, ref, onMounted: () => {},
    membershipPreview: () => '', membershipChangeLabel: () => '',
    useAuthStore: () => ({
      user: { id: 7 },
      hasPermission: code => roles.includes('super_admin') || permissions.includes(code),
    }),
    useListPage: (fetcher, options) => useListPage(fetcher, { ...options, immediate: false }),
    listCustomers: async params => {
      requests.push(params)
      return { data: { items: [{ id: params.owner_scope }], total: 1 } }
    },
  }
  const executable = source.replace(/^import\s[\s\S]*?from\s+['"][^'"]+['"]\s*$/gm, '').replace(/^export /gm, '')
  vm.runInNewContext(`${executable}\nthis.state = useDomesticCustomers()`, context)
  return { state: context.state, requests }
}

test('ownership and the independent customer permission control row eligibility', () => {
  const { state } = createState({ permissions: ['domestic:admin', 'domestic:read_all'] })
  assert.equal(state.canOperateCustomer({ owner_user_id: 7 }), true)
  assert.equal(state.canOperateCustomer({ owner_user_id: 8 }), false)
  assert.equal(state.canOperateCustomer({ owner_user_id: null }), false)
  for (const access of [{ permissions: ['domestic_customer:admin'] }, { roles: ['super_admin'] }]) {
    const { state: admin } = createState(access)
    assert.equal(admin.canOperateCustomer({ owner_user_id: 8 }), true)
    assert.equal(admin.canOperateCustomer({ owner_user_id: null }), true)
  }
})

test('customer tab changes reset pagination and retain search and region filters', async () => {
  const { state, requests } = createState()
  await state.fetchList()
  assert.equal(requests[0].owner_scope, 'private')
  state.page.value = 4
  Object.assign(state.searchForm, { owner_scope: 'public', keyword: '门店', province: '山东省', city: '青岛市' })
  await state.handleSearch()
  assert.equal(state.page.value, 1)
  assert.equal(requests[1].owner_scope, 'public')
  assert.equal(requests[1].page, 1)
  assert.equal(requests[1].keyword, '门店')
  assert.equal(requests[1].province, '山东省')
  assert.equal(requests[1].city, '青岛市')
  assert.equal(state.list.value[0].id, 'public')
})
