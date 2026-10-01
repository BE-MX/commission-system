import { statusDictionary, statusLabels, statusTypes } from '../../utils/status.js'

export const SALARY_STATUS = statusDictionary([
  ['draft', '草稿', 'info'], ['attendance_synced', '考勤已同步', 'primary'],
  ['imported', '社保已导入', 'primary'], ['calculated', '已计算', 'warning'],
  ['reviewing', '复核中', 'warning'], ['confirmed', '已锁定', 'success'],
])
export const SALARY_STATUS_LABELS = statusLabels(SALARY_STATUS)
export const SALARY_STATUS_TYPES = statusTypes(SALARY_STATUS)
