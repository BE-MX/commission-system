const STATUS = { todo: '未完成', done: '已完成', cancelled: '已取消', expired: '已过期', open: '未处理', handling: '处理中', resolved: '已解决', closed_no_action: '无需处理' }
const KIND = { content: '要点', issue: '异常', suggestion: '意见' }
const text = value => Array.isArray(value) ? value.join('、') : (value || '—')
const fields = { raw_text: '跟进原文', summary: '摘要', followup_date: '跟进日期', channel: '沟通方式',
  state_changes: '客户变化', next_date: '下次日期', next_plan: '下次计划', next_method: '下次方式',
  result_code: '本次结果', obstacles: '主要障碍', evidence_kind: '事实来源', shared_summary: '共享接手摘要', effective_progress: '有效推进' }

export function revisionChanges(revision) {
  const { before, after } = revision
  const result = []
  for (const [key, label] of Object.entries(fields)) {
    if (JSON.stringify(before[key]) !== JSON.stringify(after[key])) result.push({ label, before: text(before[key]), after: text(after[key]) })
  }
  const itemText = item => item ? [KIND[item.kind], item.text, item.category, item.severity, STATUS[item.status], item.resolution].filter(Boolean).join(' · ') : '—'
  const taskText = task => task ? [task.title, task.due_date, STATUS[task.status], task.assignee_name,
    task.closed_reason].filter(Boolean).join(' · ') : '—'
  for (const [key, label, display] of [['items', '条目', itemText], ['tasks', '关联待办', taskText],
    ['attachments', '截图', item => item ? (item.file_name || `截图 ${item.seq}`) : '—']]) {
    const oldRows = new Map((before[key] || []).map(item => [item.id, item]))
    const newRows = new Map((after[key] || []).map(item => [item.id, item]))
    for (const id of new Set([...oldRows.keys(), ...newRows.keys()])) {
      const previous = display(oldRows.get(id)), next = display(newRows.get(id))
      if (previous !== next) result.push({ label, before: previous, after: next })
    }
  }
  return result
}
