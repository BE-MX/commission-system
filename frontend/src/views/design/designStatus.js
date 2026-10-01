import { statusDictionary, statusLabels, statusTypes } from '../../utils/status.js'

export const REQUEST_STATUS = statusDictionary([
  ['pending_audit', '待审批', 'warning'], ['pending_design', '待排期', 'warning'],
  ['scheduled', '已排期', 'primary'], ['in_progress', '进行中', 'primary'],
  ['completed', '已完成', 'success'], ['rejected', '已拒绝', 'danger'],
  ['cancelled', '已取消', 'info'],
])
export const REQUEST_STATUS_LABELS = statusLabels(REQUEST_STATUS)
export const REQUEST_STATUS_TYPES = statusTypes(REQUEST_STATUS)
export const TASK_STATUS = Object.freeze(Object.fromEntries(['scheduled', 'in_progress', 'completed', 'cancelled'].map(key => [key, REQUEST_STATUS[key]])))
export const TASK_STATUS_LABELS = statusLabels(TASK_STATUS)
export const TASK_STATUS_TYPES = statusTypes(TASK_STATUS)

// The schedule chart distinguishes work in progress from a reserved slot.
export const GANTT_STATUS = statusDictionary([
  ['pending_design', '待设计', 'warning'], ['scheduled', '已排期', 'primary'],
  ['in_progress', '进行中', 'danger'], ['completed', '已完成', 'success'],
  ['cancelled', '已取消', 'info'],
])
export const GANTT_STATUS_LABELS = statusLabels(GANTT_STATUS)
export const GANTT_STATUS_TYPES = statusTypes(GANTT_STATUS)
