import { formatBeijingDateTime } from '../../utils/datetime.js'

export const minuteTime = value => formatBeijingDateTime(value, { seconds: false })
export const directionText = direction => ({ buyer: '买家', seller: '卖家', bot: '平台机器人' }[direction] || '方向未提供')
export const visibilityLabel = row => ({ link_revoked: '已撤销，需重新关联', mapping_changed: '负责人映射已更新，需重新确认' }[row.visibility_state] || '')
export const canReadRecord = row => !['link_revoked', 'mapping_changed'].includes(row.visibility_state)
export function analysisSelection(rows) {
  if (!rows.length) return { valid: false, reason: '先选择已关联的历史资料' }
  if (rows.length > 25) return { valid: false, reason: '每次最多选择 25 条资料' }
  if (rows.some(row => !canReadRecord(row))) return { valid: false, reason: '资料需先人工重新确认关联' }
  const companyId = rows[0].link?.company_id
  if (!companyId || rows.some(row => !row.link || String(row.link.company_id) !== String(companyId))) {
    return { valid: false, reason: '所选资料必须当前关联同一位本人私海客户' }
  }
  if (rows.some(row => !row.ai_eligible)) return { valid: false, reason: '所选资料中有当前不可用于分析的快照，请检查质量与来源授权' }
  return { valid: true, companyId: String(companyId), itemIds: rows.map(row => row.id) }
}

// One task retains its request ID, including after an uncertain transport result.
export function createRequestTask(makeId = () => {
  if (globalThis.crypto.randomUUID) return globalThis.crypto.randomUUID()
  return Array.from(globalThis.crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
}) {
  let task = null
  return {
    begin(kind, target) {
      const key = JSON.stringify([kind, target])
      if (task?.key === key) return task.id
      if (task?.uncertain) throw new Error('上次操作结果待核对，请先刷新确认')
      task = { key, id: makeId(), uncertain: false }
      return task.id
    },
    uncertain() { if (task) task.uncertain = true },
    complete() { task = null },
  }
}

// Invalidate on switching records, losing authority, revoking a link or unmounting.
export function createReadScope() {
  let generation = 0
  let controller
  return {
    clear() { generation += 1; controller?.abort() },
    begin() {
      this.clear()
      controller = new AbortController()
      const current = generation
      return { signal: controller.signal, isCurrent: () => current === generation && !controller.signal.aborted }
    },
  }
}
