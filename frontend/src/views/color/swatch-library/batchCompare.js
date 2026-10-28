// Must mirror backend swatch_library_service.describe_shift: the server value is authoritative,
// this copy only labels the client-side KPI deltas for the batch tab.
export const SHIFT_EPS = 0.3
const SHIFT_PAIRS = [['偏白缺黑', '偏黑缺白'], ['偏红缺绿', '偏绿缺红'], ['偏黄缺蓝', '偏蓝缺黄']]

export function describeShift(lab, stdLab) {
  if (!lab || !stdLab) return null
  return lab.map((v, i) => {
    const d = v - stdLab[i]
    if (Math.abs(d) < SHIFT_EPS) return null
    return SHIFT_PAIRS[i][d > 0 ? 0 : 1]
  })
}

/** Signed delta text for a batch value against the standard mean, e.g. "+0.42". */
export function signed(value, digits = 2) {
  if (value == null || Number.isNaN(value)) return '—'
  const n = Number(value)
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}`
}
