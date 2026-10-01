import test from 'node:test'
import assert from 'node:assert/strict'

import { useListPage } from '../src/composables/useListPage.js'

test('explicit reset sorting is detached, restores initial filters and fetches once; default reset retains sort', async () => {
  const calls = []
  const state = useListPage(async params => { calls.push(params); return { items: [], total: 0 } }, { immediate: false, searchForm: { keyword: '' }, sortParams: { sort_field: 'created_at', sort_order: 'desc' } })
  state.searchForm.keyword = 'submitted'; await state.handleSearch()
  await state.handleSortChange({ sort_field: 'model', sort_order: 'asc' })
  state.searchForm.keyword = 'draft'; state.page.value = 3
  const count = calls.length, defaults = { sort_field: 'created_at', sort_order: 'desc' }
  await state.handleReset({ sortParams: defaults }); defaults.sort_field = 'changed later'
  assert.equal(calls.length, count + 1)
  assert.deepEqual(calls.at(-1), { keyword: '', sort_field: 'created_at', sort_order: 'desc', page: 1, page_size: 20 })
  await state.handleReset(); assert.equal(calls.at(-1).sort_field, 'created_at')
})

function deferred() {
  let resolve, reject
  const promise = new Promise((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}

test('列表只允许最新请求更新数据和 loading', async () => {
  const first = deferred()
  const second = deferred()
  let callCount = 0
  const state = useListPage(
    () => (++callCount === 1 ? first.promise : second.promise),
    { immediate: false },
  )

  const firstRequest = state.fetchList()
  const secondRequest = state.fetchList()
  second.resolve({ items: ['新数据'], total: 1 })
  await secondRequest

  assert.equal(state.loading.value, false)
  assert.deepEqual(state.list.value, ['新数据'])
  assert.equal(state.total.value, 1)

  first.resolve({ items: ['旧数据'], total: 99 })
  await firstRequest

  assert.equal(state.loading.value, false)
  assert.deepEqual(state.list.value, ['新数据'])
  assert.equal(state.total.value, 1)
})

test('initial failure is an error rather than an empty result, and retry recovers', async () => {
  let attempts = 0
  const state = useListPage(async () => {
    if (++attempts === 1) throw new Error('network unavailable')
    return { items: ['recovered'], total: 1 }
  }, { immediate: false })

  assert.equal(await state.fetchList(), false)
  assert.equal(state.loading.value, false)
  assert.equal(state.hasLoaded.value, false)
  assert.equal(state.isEmpty.value, false)
  assert.equal(state.errorMessage.value, 'network unavailable')
  assert.equal(await state.fetchList(), true)
  assert.equal(state.error.value, null)
  assert.equal(state.hasLoaded.value, true)
  assert.deepEqual(state.list.value, ['recovered'])
})

test('refresh failure retains the last successful rows and identifies their page', async () => {
  let fail = false
  const state = useListPage(async () => {
    if (fail) throw new Error('refresh failed')
    return { items: ['saved result'], total: 45 }
  }, { immediate: false })
  await state.handlePageChange(2)
  fail = true
  assert.equal(await state.handlePageChange(3), false)
  assert.deepEqual(state.list.value, ['saved result'])
  assert.equal(state.total.value, 45)
  assert.equal(state.dataPage.value, 2)
  assert.equal(state.page.value, 3)
  assert.equal(state.isStale.value, true)
  assert.equal(state.isEmpty.value, false)
})

test('draft fields including dates stay unapplied during pagination, size changes and refresh', async () => {
  const requests = []
  const initial = { keyword: '', dateRange: ['2026-09-01', '2026-09-30'] }
  const state = useListPage(async params => {
    requests.push(params)
    return { items: [], total: 100 }
  }, { immediate: false, searchForm: initial })
  state.searchForm.keyword = 'applied'
  await state.handleSearch()
  state.searchForm.keyword = 'draft'
  state.searchForm.dateRange[0] = '2026-08-01'
  assert.equal(state.hasPendingSearch.value, true)
  assert.equal(initial.dateRange[0], '2026-09-01')
  await state.handlePageChange(2)
  await state.handleSizeChange(50)
  await state.fetchList()
  for (const request of requests) {
    assert.equal(request.keyword, 'applied')
    assert.deepEqual(request.dateRange, ['2026-09-01', '2026-09-30'])
  }
  state.page.value = 3
  await state.handleSearch()
  assert.equal(requests.at(-1).page, 1)
  assert.equal(requests.at(-1).keyword, 'draft')
  assert.equal(state.hasPendingSearch.value, false)
})

test('reset clears added fields and restores a detached initial snapshot on page one', async () => {
  const requests = []
  const state = useListPage(async params => {
    requests.push(params)
    return { items: [], total: 0 }
  }, { immediate: false, searchForm: { keyword: '', nested: { values: [] } } })
  state.searchForm.keyword = 'edited'
  state.searchForm.nested.values.push('changed')
  state.searchForm.extra = 'obsolete'
  state.page.value = 5
  await state.handleReset()
  assert.deepEqual(requests.at(-1), { keyword: '', nested: { values: [] }, page: 1, page_size: 20 })
  assert.equal('extra' in state.searchForm, false)
  state.searchForm.nested.values.push('again')
  await state.handleReset()
  assert.deepEqual(state.searchForm.nested.values, [])
})

test('superseded failures are settled without disturbing the current error or loading', async () => {
  const old = deferred(), current = deferred(), contexts = []
  const state = useListPage((params, context) => {
    contexts.push(context)
    return contexts.length === 1 ? old.promise : current.promise
  }, { immediate: false })
  const oldRequest = state.fetchList(), currentRequest = state.fetchList()
  assert.equal(contexts[0].signal.aborted, true)
  assert.equal(contexts[0].isCurrent(), false)
  old.reject(new Error('stale failure'))
  await oldRequest
  assert.equal(state.loading.value, true)
  assert.equal(state.error.value, null)
  current.resolve({ items: ['current'], total: 1 })
  await currentRequest
  assert.equal(state.loading.value, false)
  assert.deepEqual(state.list.value, ['current'])
})

test('mutation refresh strategies use applied conditions and preserve or move the page deliberately', async () => {
  const requests = []
  const state = useListPage(async params => {
    requests.push(params)
    return { items: [params.page], total: 80 }
  }, { immediate: false, searchForm: { keyword: 'active' } })
  await state.handlePageChange(3)
  state.searchForm.keyword = 'unsubmitted'
  await state.refreshUpdate()
  assert.equal(requests.at(-1).page, 3)
  await state.refreshCreate({ firstPage: false })
  assert.equal(requests.at(-1).page, 3)
  await state.refreshCreate()
  assert.equal(requests.at(-1).page, 1)
  assert.ok(requests.every(request => request.keyword === 'active'))
})

test('removing the last row of a page refetches the last valid page using the server total', async () => {
  const requests = []
  const state = useListPage(async params => {
    requests.push(params)
    return { items: params.page > 2 ? [] : ['remaining'], total: 40 }
  }, { immediate: false })
  state.page.value = 3
  assert.equal(await state.refreshRemove(), true)
  assert.deepEqual(requests.map(request => request.page), [3, 2])
  assert.equal(state.page.value, 2)
  assert.equal(state.dataPage.value, 2)
  assert.deepEqual(state.list.value, ['remaining'])
})

test('a failed refresh after a successful mutation does not reject as if the mutation failed', async () => {
  const state = useListPage(async () => { throw new Error('list read failed') }, { immediate: false })
  state.page.value = 4
  assert.equal(await state.refreshRemove(), false)
  assert.equal(state.page.value, 4)
  assert.equal(state.errorMessage.value, 'list read failed')
})
