export function parseProductName(name) {
  if (!name) return { type: '', size: '', color: '', weight: '' }
  const parts = name.split('/')
  const n = parts.length
  const type = parts[0] || ''
  const size = parts[1] || ''
  const color = (n >= 5 && parts[n - 3].startsWith('#'))
    ? `${parts[n - 3]}/${parts[n - 2]}`
    : (parts[n - 2] || '')
  const weight = parts[n - 1] || ''
  return { type, size, color, weight }
}

export const sourceLabel = value => ({ '': '未设置', manual: '手动', formula: '公式估算', tft: 'TFT预测' })[value] || value
export const sourceTagType = value => ({ '': 'info', manual: 'primary', formula: 'warning', tft: 'success' })[value] || 'info'

export function headerStyle() {
  return { background: 'linear-gradient(135deg,#faf8f3,#f0ece3)', fontWeight: 600, color: '#4a4a5a' }
}

export function isCurrentProgressStep(progress, step) {
  const firstPending = progress?.steps?.find(item => item.status === 0)
  return Boolean(firstPending && step.id === firstPending.id)
}
