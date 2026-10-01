import { getFilterOptions } from '@/api/stock'
import { getProgress, initProgress } from '@/api/production'

export async function loadStockFilterOptions(_, { signal }) {
  const result = await getFilterOptions({ signal, suppressToast: true })
  const data = result.data
  return Object.fromEntries(['models', 'types', 'sizes', 'colors', 'weights'].map(key => [key, data?.[key] || []]))
}

export async function loadStockProgress(itemId, { signal, isCurrent }) {
  const config = { signal, suppressToast: true, suppressNotFound: true, showLoading: false }
  try {
    const result = await getProgress(itemId, config)
    return result.data ?? result
  } catch (error) {
    // Only a missing route may initialize progress. Network/server failures remain retryable.
    if (error.response?.status !== 404) throw error
    if (!isCurrent()) return null
    await initProgress(itemId)
    if (!isCurrent()) return null
    const result = await getProgress(itemId, config)
    return result.data ?? result
  }
}
