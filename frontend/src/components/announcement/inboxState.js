/** Inbox request ownership and read acknowledgement, independent of rendering. */
export const ANNOUNCEMENT_PERMISSIONS = ['announcement:read', 'announcement:write', 'announcement:admin']

export function initialInboxState() {
  return {
    open: false, items: [], detail: null, filter: 'all', page: 1, pageSize: 20,
    total: 0, announcementCount: 0, unreadCount: 0,
    listLoading: false, detailLoading: false, readSaving: false, markingAll: false,
    listError: '', detailError: '', readError: '', status: '',
  }
}

function errorMessage(error, fallback) {
  const message = error?.response?.data?.detail || error?.response?.data?.message
  return typeof message === 'string' ? message : fallback
}

export function createInboxController({ state, api, afterRender = () => Promise.resolve() }) {
  let session = 0, listRequest = 0, detailRequest = 0, countsVersion = 0
  let mutations = Promise.resolve(), abort = new AbortController()
  const options = () => ({ signal: abort.signal })
  const counts = data => {
    state.unreadCount = Math.max(0, Number(data.unread_count) || 0)
    state.announcementCount = Math.max(0, Number(data.announcement_count ?? data.total) || 0)
  }

  function reset() {
    session++; listRequest++; detailRequest++; countsVersion++
    abort.abort(); abort = new AbortController(); mutations = Promise.resolve()
    Object.assign(state, initialInboxState())
  }

  function close() {
    state.open = false; detailRequest++
    state.detailLoading = false; state.readSaving = false
  }

  async function refreshSummary() {
    const owner = session, version = countsVersion
    try {
      const data = await api.summary(options())
      if (owner === session && version === countsVersion) counts(data)
    } catch (error) {
      if (owner === session && !abort.signal.aborted) {
        console.warn('Announcement summary unavailable', error?.response?.status || 'network')
      }
    }
  }

  async function loadList() {
    const owner = session, request = ++listRequest, version = countsVersion
    state.listLoading = true; state.listError = ''
    try {
      const data = await api.list({ page: state.page, page_size: state.pageSize, unread_only: state.filter === 'unread' }, options())
      if (owner !== session || request !== listRequest) return
      if (version !== countsVersion) {
        if (state.open) return loadList()
        return
      }
      const lastPage = Math.max(1, Math.ceil(data.total / state.pageSize))
      if (state.page > lastPage) {
        state.page = lastPage
        return loadList()
      }
      state.items = data.items; state.total = data.total
      if (version === countsVersion) counts(data)
    } catch (error) {
      if (owner === session && request === listRequest) {
        state.listError = errorMessage(error, '公告加载失败，请重试')
      }
    } finally {
      if (owner === session && request === listRequest) state.listLoading = false
    }
  }

  function enqueue(task) {
    countsVersion++ // Earlier background/list responses cannot overwrite a read.
    const next = mutations.then(task)
    mutations = next.catch(() => {}) // Task itself renders its error; keep queue usable.
    return next
  }

  async function acknowledge(detail, request, owner) {
    if (detail.is_read) return
    state.readSaving = true; state.readError = ''
    await enqueue(async () => {
      if (owner !== session || request !== detailRequest || !state.open) return
      try {
        const result = await api.markRead(detail.id, detail.revision_id, options())
        if (owner !== session) return
        countsVersion++ // Invalidate snapshots requested while this write was pending.
        counts(result)
        const row = state.items.find(item => item.id === detail.id && item.revision_id === detail.revision_id)
        if (row) row.is_read = true
        if (state.detail?.id === detail.id && state.detail.revision_id === detail.revision_id) {
          state.detail.is_read = true
          state.status = state.unreadCount ? `已标记已读 · 剩余 ${state.unreadCount} 条未读` : '全部公告已读'
        }
        if (state.open && state.filter === 'unread') await loadList()
      } catch (error) {
        if (owner === session && request === detailRequest && state.open) {
          state.readError = errorMessage(error, '已读状态保存失败，请重试')
          state.status = ''
        }
      }
    })
    if (owner === session && request === detailRequest) state.readSaving = false
  }

  async function selectNotice(id) {
    const owner = session, request = ++detailRequest
    state.detail = null; state.detailLoading = true; state.detailError = ''; state.readError = ''
    state.readSaving = false; state.status = ''
    try {
      const detail = await api.detail(id, options())
      if (owner !== session || request !== detailRequest || !state.open) return
      state.detail = detail; state.detailLoading = false
      await afterRender(detail)
      if (owner !== session || request !== detailRequest || !state.open) return
      await acknowledge(detail, request, owner)
    } catch (error) {
      if (owner === session && request === detailRequest && state.open) {
        state.detail = null
        state.detailError = errorMessage(error, '公告详情加载失败，请重新打开')
      }
    } finally {
      if (owner === session && request === detailRequest) state.detailLoading = false
    }
  }

  async function open() {
    state.open = true; state.detail = null; state.detailError = ''; state.readError = ''; state.status = ''
    detailRequest++; state.page = 1; state.filter = 'all'
    await loadList()
  }

  async function changeFilter(filter) {
    detailRequest++; state.detail = null; state.detailLoading = false; state.readSaving = false
    state.detailError = ''; state.readError = ''; state.filter = filter; state.page = 1
    await loadList()
  }

  async function markAllRead() {
    const owner = session
    state.markingAll = true; state.readError = ''
    await enqueue(async () => {
      if (owner !== session) return
      try {
        const result = await api.markAll(options())
        if (owner !== session) return
        countsVersion++
        counts(result)
        state.status = state.unreadCount ? `已更新 · 剩余 ${state.unreadCount} 条未读` : '全部公告已读 · 未读提醒已清除'
        // Requery instead of marking versions returned by an older list as read.
        await loadList()
        if (state.detail) {
          const data = await api.detail(state.detail.id, options())
          if (owner === session && state.detail?.revision_id === data.revision_id) state.detail.is_read = data.is_read
        }
      } catch (error) {
        if (owner === session) state.readError = errorMessage(error, '已读状态保存失败，请重试')
      }
    })
    if (owner === session) state.markingAll = false
  }

  async function nextUnread() {
    const owner = session, request = ++detailRequest, version = countsVersion
    try {
      const data = await api.list({ unread_only: true, page: 1, page_size: 1 }, options())
      if (owner !== session || request !== detailRequest || !state.open) return
      if (version !== countsVersion) return nextUnread()
      counts(data)
      if (data.items.length) await selectNotice(data.items[0].id)
      else state.status = '全部公告已读'
    } catch (error) {
      if (owner === session) state.readError = errorMessage(error, '公告加载失败，请重试')
    }
  }

  function back() {
    detailRequest++; state.detail = null; state.detailError = ''; state.detailLoading = false; state.readSaving = false
  }

  return { reset, close, open, refreshSummary, loadList, selectNotice, changeFilter, markAllRead, nextUnread, back,
    retryRead: () => state.detail && acknowledge(state.detail, detailRequest, session) }
}
