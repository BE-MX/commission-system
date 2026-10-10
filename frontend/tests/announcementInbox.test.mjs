import test from 'node:test'
import assert from 'node:assert/strict'
import { initialInboxState, createInboxController } from '../src/components/announcement/inboxState.js'

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}
function fixture(overrides = {}, afterRender) {
  const state = initialInboxState()
  const calls = []
  const item = { id: 1, revision_id: 10, title: 'Notice', is_read: false, content_json: { type: 'doc', content: [] } }
  const api = {
    summary: async () => ({ total: 1, unread_count: 1 }),
    list: async () => ({ items: [{ ...item }], total: 1, announcement_count: 1, unread_count: 1 }),
    detail: async () => ({ ...item }),
    markRead: async (...args) => { calls.push(args); return { total: 1, unread_count: 0 } },
    markAll: async () => ({ total: 1, unread_count: 0 }),
    ...overrides,
  }
  return { state, calls, controller: createInboxController({ state, api, afterRender }) }
}

test('opening the inbox does not mark anything read; rendering precedes acknowledgement', async () => {
  const rendered = deferred()
  const { state, controller, calls } = fixture({}, () => rendered.promise)
  await controller.open()
  assert.equal(state.unreadCount, 1)
  assert.equal(calls.length, 0)
  const viewing = controller.selectNotice(1)
  await Promise.resolve()
  assert.equal(state.detail.title, 'Notice')
  assert.equal(calls.length, 0)
  rendered.resolve()
  await viewing
  assert.equal(state.unreadCount, 0)
  assert.equal(state.items[0].is_read, true)
})

test('failed detail or read requests preserve unread counts and support retry', async () => {
  let fail = true
  const { state, controller } = fixture({ markRead: async () => {
    if (fail) throw new Error('offline')
    return { total: 1, unread_count: 0 }
  } })
  await controller.open(); await controller.selectNotice(1)
  assert.equal(state.unreadCount, 1)
  assert.equal(state.detail.is_read, false)
  assert.ok(state.readError)
  fail = false
  await controller.retryRead()
  assert.equal(state.unreadCount, 0)
  const broken = fixture({ detail: async () => { throw new Error('offline') } })
  await broken.controller.open(); await broken.controller.selectNotice(1)
  assert.equal(broken.state.unreadCount, 1)
  assert.ok(broken.state.detailError)
  assert.equal(broken.calls.length, 0)
})

test('out-of-order details and closed dialogs never acknowledge unseen notices', async () => {
  const slow = deferred()
  const { state, controller, calls } = fixture({ detail: id => id === 1 ? slow.promise : Promise.resolve({ id: 2, revision_id: 20, is_read: true }) })
  await controller.open()
  const first = controller.selectNotice(1)
  await controller.selectNotice(2)
  slow.resolve({ id: 1, revision_id: 10, is_read: false })
  await first
  assert.equal(state.detail.id, 2)
  assert.equal(calls.length, 0)
  const other = deferred()
  const closed = fixture({ detail: () => other.promise })
  await closed.controller.open()
  const loading = closed.controller.selectNotice(1)
  closed.controller.close()
  other.resolve({ id: 1, revision_id: 10, is_read: false })
  await loading
  assert.equal(closed.calls.length, 0)
})

test('old summary and old-user responses cannot overwrite a newer read/session', async () => {
  const oldSummary = deferred()
  const { state, controller } = fixture({ summary: () => oldSummary.promise })
  await controller.open()
  const refreshing = controller.refreshSummary()
  await controller.selectNotice(1)
  oldSummary.resolve({ total: 1, unread_count: 1 })
  await refreshing
  assert.equal(state.unreadCount, 0)
  const oldList = deferred()
  const switched = fixture({ list: () => oldList.promise })
  const opening = switched.controller.open()
  switched.controller.reset()
  oldList.resolve({ items: [{ id: 99 }], total: 9, unread_count: 9 })
  await opening
  assert.deepEqual(switched.state.items, [])
  assert.equal(switched.state.unreadCount, 0)
})

test('empty and fully read lists are safe and next-unread handles zero', async () => {
  const { state, controller } = fixture({ list: async () => ({ items: [], total: 0, announcement_count: 0, unread_count: 0 }) })
  await controller.open(); await controller.nextUnread(); await controller.markAllRead()
  assert.equal(state.unreadCount, 0)
  assert.equal(state.detail, null)
  assert.deepEqual(state.items, [])
})

test('snapshots requested during a write cannot restore unread counts or rows', async () => {
  const write = deferred(), staleList = deferred(), staleSummary = deferred()
  let listCalls = 0, started = deferred()
  const { state, controller } = fixture({
    markRead: () => { started.resolve(); return write.promise },
    summary: () => staleSummary.promise,
    list: async () => {
      listCalls++
      if (listCalls === 1) return { items: [{ id: 1, revision_id: 10, is_read: false }], total: 1, unread_count: 1 }
      if (listCalls === 2) return staleList.promise
      return { items: [], total: 0, announcement_count: 1, unread_count: 0 }
    },
  })
  await controller.open()
  const reading = controller.selectNotice(1)
  await started.promise
  const filtering = controller.changeFilter('unread'), refreshing = controller.refreshSummary()
  write.resolve({ total: 1, unread_count: 0 })
  await reading
  staleSummary.resolve({ total: 1, unread_count: 1 })
  staleList.resolve({ items: [{ id: 1, revision_id: 10, is_read: false }], total: 1, unread_count: 1 })
  await Promise.all([filtering, refreshing])
  assert.equal(state.unreadCount, 0)
  assert.deepEqual(state.items, [])
  assert.equal(listCalls, 3)
  assert.equal(state.listLoading, false)
})

test('an old-user bulk write response cannot update a reset session', async () => {
  const write = deferred(), started = deferred()
  const { state, controller } = fixture({ markAll: () => { started.resolve(); return write.promise } })
  await controller.open()
  const marking = controller.markAllRead()
  await started.promise
  controller.reset()
  write.resolve({ total: 9, unread_count: 8 })
  await marking
  assert.equal(state.unreadCount, 0)
  assert.equal(state.announcementCount, 0)
  assert.equal(state.markingAll, false)
})

test('reading in unread filter refreshes membership and clamps an empty last page', async () => {
  let read = false
  const { state, controller } = fixture({
    markRead: async () => { read = true; return { total: 1, unread_count: 0 } },
    list: async () => ({ items: read ? [] : [{ id: 1, revision_id: 10, is_read: false }], total: read ? 0 : 21, announcement_count: 21, unread_count: read ? 0 : 21 }),
  })
  await controller.open(); await controller.changeFilter('unread')
  state.page = 2
  await controller.loadList(); await controller.selectNotice(1)
  assert.equal(state.unreadCount, 0)
  assert.deepEqual(state.items, [])
  assert.equal(state.total, 0)
  assert.equal(state.page, 1)
  assert.equal(state.detail.is_read, true)
})
