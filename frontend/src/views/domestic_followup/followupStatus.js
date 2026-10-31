/** 跟进域的状态字典：标签色调统一从这里取（DESIGN.md 状态标签 type 从字典取，el-tag 不写静态 type）。 */
import { statusDictionary } from '@/utils/status'

export const TASK_TYPE_STATUS = statusDictionary([
  ['receipt', '收货回访', 'success'], ['plan', '约定跟进', 'primary'],
  ['issue', '异常', 'danger'], ['suggestion', '意见', 'warning'],
])

export const ITEM_KIND_STATUS = statusDictionary([
  ['issue', '异常', 'danger'], ['suggestion', '意见', 'warning'],
])

export const SEVERITY_STATUS = statusDictionary([['紧急', '紧急', 'danger'], ['一般', '一般', 'info']])
