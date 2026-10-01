import test from 'node:test'
import assert from 'node:assert/strict'
import { nextTick } from 'vue'
import { readFileSync } from 'node:fs'
import { viewController } from './helpers/viewController.mjs'

const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }
function employee(t, read) {
  return viewController(t, '../../src/views/employee/EmployeeAttribute.vue', 'openHistory,historyList,historyVisible,historyEmployee,historyResource,fetchHistory,openSetDialog,currentRow', {
    '@/api/employee': { getAttributeHistory: read },
  })
}
function supervisor(t, read) {
  return viewController(t, '../../src/views/supervisor/SupervisorRelation.vue', 'openHistory,historyList,historyVisible,historyRow,historyResource,fetchHistory,openSetDialog,currentRow', {
    '@/api/supervisor': { getSupervisorHistory: read },
  })
}
function store(t, api = {}, userApi = {}, feedback = {}) {
  return viewController(t, '../../src/views/expo/StoreManagement.vue', 'openUsers,usersVisible,usersStore,usersResource,fetchStoreUsers,storeUsers,bindForm,handleBind,handleUnbind,openQuota,userResource,userOptions,userQuery,searchUsers', {
    '@/api/expo': { getStoreUsers: async () => ({ data: [] }), ...api },
    '@/api/userManagement': { getUserList: async () => ({ data: { items: [] } }), ...userApi },
    '@/utils/feedback': { msgSuccess() {}, msgError() {}, confirmDanger: async () => {}, ...feedback },
  })
}

test('employee history ignores former employee responses and keeps its scope separate from the edit dialog', async t => {
  const old = deferred()
  const { vm } = employee(t, async params => params.employee_id === 'A' ? old.promise : { data: [{ id: 'B' }] })
  const pending = vm.openHistory({ user_id: 'A' }); await vm.openHistory({ user_id: 'B' })
  old.resolve({ data: [{ id: 'A' }] }); await pending
  assert.equal(vm.historyList.value[0].id, 'B'); vm.openSetDialog({ user_id: 'C' })
  assert.equal(vm.historyEmployee.value.user_id, 'B'); await vm.fetchHistory(); assert.equal(vm.historyList.value[0].id, 'B')
})

test('employee history first error is distinct from empty and retries; later errors preserve history', async t => {
  let fail = true
  const { vm } = employee(t, async (_, config) => { assert.ok(config.signal); assert.equal(config.suppressToast, true); if (fail) throw Error('history offline'); return { data: [{ id: 3 }] } })
  await vm.openHistory({ user_id: 'A' }); assert.equal(vm.historyResource.errorMessage.value, 'history offline'); assert.equal(vm.historyResource.isEmpty.value, false)
  fail = false; await vm.fetchHistory(); fail = true; await vm.fetchHistory()
  assert.equal(vm.historyList.value[0].id, 3); assert.equal(vm.historyResource.isStale.value, true)
  fail = false; await vm.fetchHistory(); assert.equal(vm.historyResource.errorMessage.value, '')
})

test('closing employee history cancels its pending read and clears its scope', async t => {
  const old = deferred(); let signal
  const { vm } = employee(t, async (_, config) => { signal = config.signal; return old.promise })
  const pending = vm.openHistory({ user_id: 'A' }); vm.historyVisible.value = false; await nextTick()
  assert.equal(signal.aborted, true); old.resolve({ data: [{ id: 1 }] }); await pending
  assert.deepEqual(vm.historyList.value, []); assert.equal(vm.historyEmployee.value, null)
})

test('store users ignore former store responses and quota scope does not change the users scope', async t => {
  const old = deferred(), ids = []
  const { vm } = store(t, { getStoreUsers: async id => { ids.push(id); return id === 1 ? old.promise : { data: [{ user_id: id }] } } })
  const pending = vm.openUsers({ id: 1 }); await vm.openUsers({ id: 2 }); old.resolve({ data: [{ user_id: 1 }] }); await pending
  assert.equal(vm.storeUsers.value[0].user_id, 2); vm.openQuota({ id: 3 }); await vm.fetchStoreUsers()
  assert.equal(vm.usersStore.value.id, 2); assert.equal(ids.at(-1), 2)
})

test('store users expose first error and retry; same store refresh errors retain successful users', async t => {
  let fail = true
  const { vm } = store(t, { getStoreUsers: async (_, config) => { assert.ok(config.signal); assert.equal(config.suppressToast, true); if (fail) throw Error('bindings offline'); return { data: [{ user_id: 4 }] } } })
  await vm.openUsers({ id: 2 }); assert.equal(vm.usersResource.isEmpty.value, false); assert.equal(vm.usersResource.errorMessage.value, 'bindings offline')
  fail = false; await vm.fetchStoreUsers(); fail = true; await vm.fetchStoreUsers()
  assert.equal(vm.storeUsers.value[0].user_id, 4); assert.equal(vm.usersResource.isStale.value, true)
  fail = false; await vm.fetchStoreUsers(); assert.equal(vm.usersResource.errorMessage.value, '')
})

test('closing store users clears and cancels both bindings and user suggestions', async t => {
  const old = deferred(), suggestions = deferred(); let bindingSignal, userSignal
  const { vm } = store(t, { getStoreUsers: async (_, config) => { bindingSignal = config.signal; return old.promise } },
    { getUserList: async (_, config) => { userSignal = config.signal; return suggestions.promise } })
  const pending = vm.openUsers({ id: 1 }), search = vm.searchUsers('old'); vm.usersVisible.value = false; await nextTick()
  assert.equal(bindingSignal.aborted, true); assert.equal(userSignal.aborted, true)
  old.resolve({ data: [{ user_id: 1 }] }); suggestions.resolve({ data: { items: [{ id: 1 }] } }); await Promise.all([pending, search])
  assert.deepEqual(vm.storeUsers.value, []); assert.deepEqual(vm.userOptions.value, []); assert.equal(vm.usersStore.value, null)
})

test('user suggestions use latest query, retain previous success after failure and retry their applied query', async t => {
  const old = deferred(); let fail = false; const reads = []
  const { vm } = store(t, {}, { getUserList: async (params, config) => {
    reads.push(params); assert.ok(config.signal); assert.equal(config.suppressToast, true)
    if (params.keyword === 'old') return old.promise
    if (fail) throw Error('suggestions offline')
    return { data: { items: [{ id: params.keyword }] } }
  } })
  await vm.openUsers({ id: 2 }); const pending = vm.searchUsers('old'); await vm.searchUsers('new')
  old.resolve({ data: { items: [{ id: 'old' }] } }); await pending; assert.equal(vm.userOptions.value[0].id, 'new')
  fail = true; await vm.searchUsers('new'); assert.equal(vm.userResource.isStale.value, true)
  fail = false; await vm.searchUsers(vm.userQuery.value); assert.equal(reads.at(-1).page_size, 20); assert.equal(reads.at(-1).keyword, 'new')
})

test('binding success is preserved when its subsequent users read fails', async t => {
  let fail = false; const messages = [], writes = []
  const { vm } = store(t, { getStoreUsers: async () => { if (fail) throw Error('saved bindings offline'); return { data: [{ user_id: 4 }] } },
    bindStoreUser: async (id, payload) => { writes.push({ id, payload }); fail = true } }, {}, { msgSuccess: text => messages.push(text) })
  await vm.openUsers({ id: 2 }); vm.bindForm.user_id = 5; vm.bindForm.is_primary = true; await vm.handleBind()
  assert.deepEqual(writes, [{ id: 2, payload: { user_id: 5, is_primary: true } }]); assert.deepEqual(messages, ['绑定'])
  assert.equal(vm.bindForm.user_id, null); assert.equal(vm.usersResource.errorMessage.value, 'saved bindings offline'); assert.equal(vm.storeUsers.value[0].user_id, 4)
})

test('late binding success does not clear the new store form or refresh it with the old scope', async t => {
  const write = deferred(), ids = []
  const { vm } = store(t, { getStoreUsers: async id => { ids.push(id); return { data: [] } }, bindStoreUser: async () => write.promise })
  await vm.openUsers({ id: 1 }); vm.bindForm.user_id = 5; const pending = vm.handleBind()
  await vm.openUsers({ id: 2 }); vm.bindForm.user_id = 6; write.resolve(); await pending
  assert.equal(vm.bindForm.user_id, 6); assert.deepEqual(ids, [1, 2])
})

test('unbind confirmation cannot move a write to another store, and keeps the existing confirmation text', async t => {
  const confirmation = deferred(), writes = [], confirms = []
  const { vm } = store(t, { unbindStoreUser: async (...args) => writes.push(args) }, {}, { confirmDanger: async (...args) => { confirms.push(args); return confirmation.promise } })
  await vm.openUsers({ id: 1 }); const pending = vm.handleUnbind({ user_id: 5, username: 'user5' })
  await vm.openUsers({ id: 2 }); confirmation.resolve(); await pending
  assert.deepEqual(writes, []); assert.deepEqual(confirms[0], ['解绑', '账号 user5', '解绑后该账号将不能再看本店线索与额度。'])
})

test('supervisor history preserves its salesperson scope through late reads and separate editing', async t => {
  const old = deferred()
  const { vm } = supervisor(t, async params => params.salesperson_id === 'A' ? old.promise : { data: [{ id: 'B' }] })
  const pending = vm.openHistory({ salesperson_id: 'A' }); await vm.openHistory({ salesperson_id: 'B' })
  old.resolve({ data: [{ id: 'A' }] }); await pending
  assert.equal(vm.historyList.value[0].id, 'B'); vm.openSetDialog({ salesperson_id: 'C' }); await vm.fetchHistory()
  assert.equal(vm.historyRow.value.salesperson_id, 'B'); assert.equal(vm.historyList.value[0].id, 'B')
})

test('supervisor history first error retries and refresh failure keeps previous records', async t => {
  let fail = true
  const { vm } = supervisor(t, async (_, config) => { assert.ok(config.signal); assert.equal(config.suppressToast, true); if (fail) throw Error('supervisor history offline'); return { data: [{ id: 3 }] } })
  await vm.openHistory({ salesperson_id: 'A' }); assert.equal(vm.historyResource.errorMessage.value, 'supervisor history offline'); assert.equal(vm.historyResource.isEmpty.value, false)
  fail = false; await vm.fetchHistory(); fail = true; await vm.fetchHistory()
  assert.equal(vm.historyList.value[0].id, 3); assert.equal(vm.historyResource.isStale.value, true)
  fail = false; await vm.fetchHistory(); assert.equal(vm.historyResource.errorMessage.value, '')
})

test('supervisor history close cancels late response and removes prior salesperson data', async t => {
  const old = deferred(); let signal
  const { vm } = supervisor(t, async (_, config) => { signal = config.signal; return old.promise })
  const pending = vm.openHistory({ salesperson_id: 'A' }); vm.historyVisible.value = false
  assert.equal(signal.aborted, true); old.resolve({ data: [{ id: 1 }] }); await pending
  assert.deepEqual(vm.historyList.value, []); assert.equal(vm.historyRow.value, null)
})

for (const [label, controller, key] of [['employee', employee, 'user_id'], ['supervisor', supervisor, 'salesperson_id']]) {
  test(`${label} changing to a failed history scope does not present the former person's records`, async t => {
    const { vm } = controller(t, async params => {
      if (Object.values(params)[0] === 'B') throw Error('new person offline')
      return { data: [{ id: 'A' }] }
    })
    await vm.openHistory({ [key]: 'A' }); await vm.openHistory({ [key]: 'B' })
    assert.deepEqual(vm.historyList.value, []); assert.equal(vm.historyResource.hasLoaded.value, false)
    assert.equal(vm.historyResource.errorMessage.value, 'new person offline')
  })
}

test('new store read failure clears former bindings instead of exposing wrong-store unbind actions', async t => {
  const { vm } = store(t, { getStoreUsers: async id => { if (id === 2) throw Error('new store offline'); return { data: [{ user_id: 1 }] } } })
  await vm.openUsers({ id: 1 }); await vm.openUsers({ id: 2 })
  assert.deepEqual(vm.storeUsers.value, []); assert.equal(vm.usersResource.hasLoaded.value, false)
  assert.equal(vm.usersResource.errorMessage.value, 'new store offline')
})

test('binding response cannot reset a reopened form even when its store ID matches the original', async t => {
  const write = deferred(), ids = []
  const { vm } = store(t, { getStoreUsers: async id => { ids.push(id); return { data: [] } }, bindStoreUser: async () => write.promise })
  await vm.openUsers({ id: 1 }); vm.bindForm.user_id = 5; const pending = vm.handleBind()
  vm.usersVisible.value = false; await vm.openUsers({ id: 1 }); vm.bindForm.user_id = 6
  write.resolve(); await pending; assert.equal(vm.bindForm.user_id, 6); assert.deepEqual(ids, [1, 1])
})

for (const [file, name, clientName, args, expectedPath, expectedParams, axiosLayer] of [
  ['employee', 'getAttributeHistory', 'request', [{ employee_id: 'A' }], '/employee/attribute/history', { employee_id: 'A' }, false],
  ['supervisor', 'getSupervisorHistory', 'request', [{ salesperson_id: 'B' }], '/supervisor/history', { salesperson_id: 'B' }, false],
  ['expo', 'getStoreUsers', 'expoClient', [7], '/stores/7/users', undefined, false],
  ['userManagement', 'getUserList', 'authRequest', [{ keyword: 'account', page: 1, page_size: 20 }], '/users/list', { keyword: 'account', page: 1, page_size: 20 }, true],
]) {
  test(`${name} actual API forwards abort/config/query and preserves its business envelope`, async () => {
    const source = readFileSync(new URL(`../src/api/${file}.js`, import.meta.url), 'utf8')
    const declaration = source.match(new RegExp(`export function ${name}\\([\\s\\S]*?\\n}`))[0].replace('export ', '')
    const calls = [], body = { data: [{ id: 1 }] }, signal = new AbortController().signal
    const client = { get: async (path, config) => { calls.push({ path, config }); return axiosLayer ? { data: body } : body } }
    const method = new Function(clientName, declaration + `;return ${name};`)(client)
    assert.equal(await method(...args, { signal, suppressToast: true }), body)
    assert.equal(calls[0].path, expectedPath); assert.deepEqual(calls[0].config.params, expectedParams)
    assert.equal(calls[0].config.signal, signal); assert.equal(calls[0].config.suppressToast, true); assert.equal(calls[0].config.showLoading, false)
  })
}
