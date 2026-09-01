import test from 'node:test'
import assert from 'node:assert/strict'

import { useListPage } from '../src/composables/useListPage.js'

function deferred() {
  let resolve
  const promise = new Promise(done => { resolve = done })
  return { promise, resolve }
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
