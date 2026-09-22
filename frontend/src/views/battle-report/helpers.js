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
  const score = p => !p.data_complete ? null : sort === 'rate' ? p.progress_percent : Number(p.gmv)
  const sorted = [...people].sort((a, b) => (score(b) ?? -1) - (score(a) ?? -1) || a.member_id - b.member_id)
  let previous, rank = 0
  return sorted.map((p, i) => {
    const value = score(p)
    if (value !== previous) rank = i + 1
    previous = value
    return { ...p, rank: value == null ? '—' : rank }
  })
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
