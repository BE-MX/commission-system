/** 任务中心文案与状态规则（纯模块，与后端 app/task/models.py、service.can_transition 同口径）。 */
export const STATUS_META = {
  todo: { label: '待办', tone: 'todo' },
  in_progress: { label: '进行中', tone: 'doing' },
  blocked: { label: '受阻', tone: 'blocked' },
  pending_confirm: { label: '待确认', tone: 'pending' },
  done: { label: '已完成', tone: 'done' },
  shelved: { label: '已搁置', tone: 'shelved' },
}
export const PRIORITY_META = {
  P0: { label: '紧急', tone: 'p0' },
  P1: { label: '高', tone: 'p1' },
  P2: { label: '中', tone: 'p2' },
  P3: { label: '低', tone: 'p3' },
}
export const PRIORITIES = Object.keys(PRIORITY_META)
export const CLOSED = new Set(['done', 'shelved'])
export const BOARD_COLUMNS = ['todo', 'in_progress', 'blocked', 'pending_confirm', 'done']
export const LINK_KIND_META = { doc: '文档', prototype: '原型', url: '链接' }
export const EVENT_LABELS = {
  created: '创建', updated: '修改字段', status_changed: '变更状态', moved: '调整父任务',
  deleted: '删除', restored: '恢复', linked: '添加关联', unlinked: '移除关联',
}
export const ACTOR_LABELS = { user: '我', ai: 'AI', reporter: '上报器', mcp: '代理' }

const OPEN = ['todo', 'in_progress', 'blocked']

/** 详情抽屉「状态」下拉的可选项：首项为当前状态，其余为用户可迁移的目标。 */
export function userStatusOptions(current) {
  if (CLOSED.has(current)) return [current, 'todo']
  if (current === 'pending_confirm') return ['pending_confirm', 'in_progress', 'done']
  return [current, ...OPEN.filter(s => s !== current), 'done', 'shelved']
}

/** today 为北京时间 YYYY-MM-DD（utils/datetime.js 的 currentBeijingDate()）。 */
export function isOverdue(task, today) {
  return Boolean(task.due_date) && task.due_date < today && !CLOSED.has(task.status)
}
