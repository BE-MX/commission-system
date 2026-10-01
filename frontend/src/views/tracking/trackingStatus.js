import { statusDictionary, statusLabels, statusTypes } from '../../utils/status.js'

export const TRACKING_STATUS = statusDictionary([
  ['pending', '待查询', 'info'], ['picked_up', '已揽收', 'primary'],
  ['in_transit', '运输中', 'primary'], ['out_for_delivery', '派送中', 'warning'],
  ['customs', '清关中', 'warning'], ['customs_hold', '海关扣留', 'danger'],
  ['delivered', '已签收', 'success'], ['returned', '已退回', 'danger'],
  ['exception', '异常', 'danger'],
])
export const TRACKING_STATUS_LABELS = statusLabels(TRACKING_STATUS)
export const TRACKING_STATUS_TYPES = statusTypes(TRACKING_STATUS)
