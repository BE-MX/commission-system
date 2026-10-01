/** Keep structured API validation errors readable in inline states and feedback. */
export function errorMessage(error, fallback = '加载失败，请重试') {
  const detail = error?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map(item => item.msg || item.message).filter(Boolean).join('；') || fallback
  if (detail && typeof detail === 'object') return detail.message || JSON.stringify(detail)
  return error?.response?.data?.message || error?.message || fallback
}
