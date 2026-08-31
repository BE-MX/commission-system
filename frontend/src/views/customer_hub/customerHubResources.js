export function createPagedResource(fetcher) {
  let requestId = 0
  return {
    items: [], total: 0, page: 1, pageSize: 20, loading: false, error: null, staleGuidance: '',
    async load(params) {
      const current = ++requestId
      this.loading = true
      this.error = null
      try {
        const response = await fetcher(params)
        if (current !== requestId) return this.items
        const data = response?.data || {}
        this.items = data.items || []
        this.total = data.total ?? this.items.length
        this.page = data.page ?? params.page
        this.pageSize = data.page_size ?? params.page_size
        this.staleGuidance = ''
      } catch (error) {
        if (current !== requestId) return this.items
        this.error = error
        this.staleGuidance = this.items.length ? '当前保留上次成功结果，数据可能已过期。' : ''
      } finally {
        if (current === requestId) this.loading = false
      }
      return this.items
    },
  }
}

export function createLatestResource(fetcher) {
  let requestId = 0
  return {
    data: null, loading: false, error: null, key: null,
    async load(key) {
      const current = ++requestId
      this.key = key
      this.data = null
      this.error = null
      this.loading = true
      try {
        const response = await fetcher(key)
        if (current === requestId) this.data = response?.data ?? null
      } catch (error) {
        if (current === requestId) this.error = error
      } finally {
        if (current === requestId) this.loading = false
      }
      return this.data
    },
    retry() { return this.load(this.key) },
    invalidate() { requestId += 1; this.loading = false },
  }
}

export function createMutationController(executor) {
  return {
    loading: false,
    error: null,
    async submit(...args) {
      if (this.loading) return false
      this.loading = true
      this.error = null
      try {
        await executor(...args)
        return true
      } catch (error) {
        this.error = error
        return false
      } finally {
        this.loading = false
      }
    },
  }
}
