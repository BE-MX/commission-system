import { statusLabels, statusTypes } from '../../utils/status.js'
export const CONCEPT_STATUS = {
  draft: { label: '草稿', tone: 'info' }, pending: { label: '待补充', tone: 'warning' },
  in_progress: { label: '填写中', tone: 'primary' }, review: { label: '待审批', tone: 'warning' },
  active: { label: '已完成', tone: 'success' }, deprecated: { label: '已废弃', tone: 'danger' },
}
export const CONCEPT_LABELS = statusLabels(CONCEPT_STATUS)
export const CONCEPT_TYPES = statusTypes(CONCEPT_STATUS)
