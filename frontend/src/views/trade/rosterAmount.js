/** Roster API amounts are non-negative decimal strings (DECIMAL(16, 2)).
 * Keep every digit: converting the largest supported amount to Number loses cents.
 */
export function formatRosterAmount(value) {
  if (typeof value !== 'string') return '—'
  const match = /^(\d+)(?:\.(\d{1,2}))?$/.exec(value.trim())
  if (!match) return '—'
  const integer = match[1].replace(/^0+(?=\d)/, '')
  const grouped = integer.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${grouped}.${(match[2] || '').padEnd(2, '0')}`
}
