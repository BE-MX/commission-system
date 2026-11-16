// 客户流失态势的展示小工具。日期一律以后端给的北京日期为基准做纯日历加减，不用客户端时区（红线 23）。

/** 'YYYY-MM-DD' + 偏移天数 → 「11 月 13 日」。 */
export function dayLabel(offset, today) {
  if (!today) return '—'
  const [year, month, day] = today.split('-').map(Number)
  const date = new Date(Date.UTC(year, month - 1, day + Math.round(offset)))
  return `${date.getUTCMonth() + 1} 月 ${date.getUTCDate()} 日`
}

/** 是否用三维：需要 WebGL、未开启减少动态、宽度够（窄屏改 2D 甲板图）。 */
export function prefers3d() {
  if (typeof window === 'undefined') return false
  if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return false
  if (window.innerWidth < 768) return false
  try {
    const canvas = document.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') || canvas.getContext('webgl'))
  } catch {
    return false
  }
}

export const CLOCK_TEXT = { follow: '跟进钟（1 个月未跟进）', order: '订单钟（3 个月未下单）' }
