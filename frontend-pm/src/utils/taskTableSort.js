import { TASK_STATUS } from './labels.js'

const textOrder = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

export function nextTaskSort(current, field) {
  if (current.field !== field) return { field, order: 'asc' }
  if (current.order === 'asc') return { field, order: 'desc' }
  return { field: '', order: '' }
}

export function sortTaskRows(tasks, sort, nameOf = value => value) {
  const fields = {
    title: task => task.title,
    status: task => TASK_STATUS[task.status]?.label || task.status,
    assignee: task => task.assignee ? nameOf(task.assignee) : null,
    due_date: task => task.due_date,
    phase: task => task.phase == null || task.phase === '' ? null : Number(task.phase),
    materials: task => task.materials?.map(material => material.name).join('、'),
  }
  const read = fields[sort.field]
  if (!read || !['asc', 'desc'].includes(sort.order)) return [...tasks]
  const missing = value => value == null || value === '' || (typeof value === 'number' && !Number.isFinite(value))
  const compare = (left, right) => typeof left === 'number' && typeof right === 'number'
    ? left - right : textOrder.compare(String(left), String(right))
  return [...tasks].sort((left, right) => {
    const a = read(left), b = read(right)
    const result = missing(a) || missing(b)
      ? Number(missing(a)) - Number(missing(b))
      : compare(a, b) * (sort.order === 'asc' ? 1 : -1)
    return result || compare(left.id, right.id)
  })
}
