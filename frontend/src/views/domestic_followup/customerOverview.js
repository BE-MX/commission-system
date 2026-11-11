export const DEAL_STATUS = {
  won: '已成交', unwon: '未成交', unknown: '待核实', sample_only: '仅样单成交',
}
export const DEAL_SOURCE = { system_order: '系统订单', historical_archive: '历史档案', manual_verification: '人工核实', manual_override: '人工修改', unverified: '待核实' }
export const COLLABORATION_STATUS = {
  unassigned: '待分配', following: '跟进中', handoff: '交接中', open: '可接手', stopped: '停止开发',
}
export const DEVELOPMENT_STAGE = {
  new: '待联系', contacted: '已联系', quoted: '报价或寄样', paused: '暂缓',
}
export const COLLABORATION_ACTION = {
  claim: '接手跟进', offer_handoff: '发起交接', request_handoff: '申请接手',
  accept_handoff: '接受交接', reject_handoff: '拒绝交接', withdraw_handoff: '撤回交接',
  add_collaborator: '添加协作人', remove_collaborator: '移除协作人', release: '释放跟进',
  deal_verified: '核实成交', deal_status_updated: '修改成交状态', deal_status_restored: '恢复自动判定',
  open: '开放接手', reassign: '重派负责人', stop: '停止开发', reopen: '恢复开发', initialize: '初始化跟进责任',
}
export const COORDINATION_REASON = {
  handoff_overdue: '待接收已满 3 天', no_progress: '长期无有效推进', development_task_overdue: '开发待办长期逾期',
  owner_ineligible: '当前负责人资格失效', recipient_ineligible: '接收人资格失效',
  customer_inactive: '客户已停用', unassigned: '待分配',
}

export const labelFor = (dictionary, value, fallback = '—') => dictionary[value] || value || fallback
export const dealLabel = row => labelFor(DEAL_STATUS, row.sample_only ? 'sample_only' : row.deal_status)
export const regionLabel = row => [row.province, row.city].filter(Boolean).join(' · ') || '待补地区'
