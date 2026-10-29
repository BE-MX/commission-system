const finite = value => value != null && Number.isFinite(Number(value))
export function paceDescription(value, { compact = false } = {}) {
  if (!finite(value)) return compact ? '待确认' : '时间进度对比待确认'
  const amount = Math.abs(Number(value)).toFixed(1)
  if (Number(amount) === 0) return compact ? '持平' : '与时间进度持平'
  return `${compact ? '' : '较时间进度'}${Number(value) > 0 ? '领先' : '落后'} ${amount} 个百分点`
}
export function rateChangeDescription(value, label = '较上期') {
  if (!finite(value)) return ''
  const amount = Math.abs(Number(value)).toFixed(1)
  return Number(amount) === 0 ? `${label}持平` : `${label}${Number(value) > 0 ? '提高' : '降低'} ${amount} 个百分点`
}
export function sprintEmptyDescription(metrics = {}, timeProgress) {
  const cells = Object.values(metrics || {})
  if (!cells.length || cells.some(cell => cell == null || !Object.hasOwn(cell, 'target'))) return '指标数据尚不完整，暂不能判断冲刺情况。'
  if (!cells.some(cell => cell?.target > 0)) return '当前范围未设置可计算的目标，暂不能判断冲刺情况。'
  if (!finite(timeProgress)) return '时间进度待确认，暂不能判断冲刺情况。'
  if (Number(timeProgress) <= 0) return '所选周期尚无工作日进度，暂不作冲刺判断。'
  if (!cells.some(cell => finite(cell?.rate))) return '完成率数据尚不完整，暂不能判断冲刺情况。'
  return '当前范围暂无冲刺提示。'
}
// Preserve complete group membership so searching never changes team subtotals.
export function findTargetGroups(groups, query) {
  const text = String(query || '').trim().toLocaleLowerCase()
  if (!text) return groups
  return groups.map(group => ({ ...group, allMembers: group.members, members: group.members.filter(person => `${group.name} ${person.name}`.toLocaleLowerCase().includes(text)) })).filter(group => group.members.length)
}
export const METRIC_GUIDE = [
  { name: 'GMV', text: '有效订单业绩金额，单位 USD；按业绩入账日期统计。' },
  { name: '新签客户', text: '选定期间内产生有效新签订单的客户数，沿用现有去重与业务员归属规则。' },
  { name: '复购客户', text: '选定期间内产生有效复购订单的客户数，沿用现有归属规则，人工裁定优先。' },
  { name: '复购金额', text: '上述有效复购订单的美元金额。' },
  { name: '时间进度', text: '已过工作日占所选周期工作日的比例；例如完成率 60%、时间进度 80%，表示落后 20 个百分点。' },
]
