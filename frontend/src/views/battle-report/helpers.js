import { formatBeijingDate, parseApiDateTime } from '../../utils/datetime.js'

export const stageLabels = { draft: '草稿', upcoming: '待开始', running: '进行中', ended: '已结束', archived: '已归档' }
const moneyFormatter = new Intl.NumberFormat('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
export const money = value => value == null ? '—' : moneyFormatter.format(String(value))
export const rate = value => value == null ? '待补全' : `${value.toFixed(1)}%`
export const errorText = error => {
  const detail = error?.response?.data?.detail
  return Array.isArray(detail) ? detail.map(item => item.msg).join('；') : detail || error?.message || '加载失败，请重试'
}
export const addDays = (day, count) => formatBeijingDate(new Date(parseApiDateTime(day).getTime() + count * 86400000))

export function rankPeople(people, sort = 'gmv') {
  const cents = value => { const [whole, fraction = ''] = String(value).split('.'); return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0')) }
  const valid = p => p.data_complete && (sort !== 'rate' || (p.progress_percent != null && Number(p.target ?? p.target_usd) > 0))
  const sorted = [...people].sort((a, b) => {
    if (valid(a) !== valid(b)) return valid(a) ? -1 : 1
    if (!valid(a)) return a.member_id - b.member_id
    const diff = sort === 'rate'
      ? cents(b.gmv) * cents(a.target ?? a.target_usd) - cents(a.gmv) * cents(b.target ?? b.target_usd)
      : cents(b.gmv) - cents(a.gmv)
    return diff > 0n ? 1 : diff < 0n ? -1 : a.member_id - b.member_id
  })
  return sorted.map((p, i) => ({ ...p, rank: valid(p) ? i + 1 : '—' }))
}

export function targetChanges(members, values) {
  const cents = value => {
    const [whole, fraction = ''] = String(value).split('.')
    return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
  }
  const changes = []
  for (const member of members.filter(m => m.can_edit)) {
    const value = String(values[member.id] ?? '').trim()
    if (!value && member.target_usd == null) continue
    if (!/^\d{1,14}(\.\d{1,2})?$/.test(value) || Number(value) <= 0) throw new Error(`${member.user_name}：目标须为正数，最多两位小数`)
    if (member.target_usd == null || cents(value) !== cents(member.target_usd)) changes.push({ member_id: member.id, version: member.version, target_usd: value })
  }
  return changes
}
