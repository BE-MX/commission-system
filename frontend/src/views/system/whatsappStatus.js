export function historyLabel(state) {
  return { unknown: '历史范围待确认', not_started: '等待平台提供历史', stalled: '历史补齐已暂停', partial: '已同步部分可用历史', syncing: '历史补齐中',
    syncing_available: '历史补齐中', synced_available: '本次可用历史已同步', available: '本次可用历史已同步',
    batch_complete: '本次历史批次结束', gap: '历史存在缺口' }[state] || '历史范围待确认'
}

export function syncLabel(state) {
  return { unknown: '等待同步', collecting: '实时接收中', protected_pause: '保护性暂停', paused: '同步已暂停', syncing: '正在同步', catching_up: '积压补齐中',
    synced_available: '已同步当前可用数据', idle: '等待新事件', gap: '同步存在缺口', error: '同步异常' }[state] || state || '等待同步'
}

export function revokeFeedback(account) {
  const confirmed = account?.status === 'revoked' && ['revoked_confirmed', 'remote_confirmed'].includes(account?.revoke_state)
  return { confirmed, text: confirmed ? '已停止采集，远端注销已确认' : '已停止方舟采集与访问；远端注销未确认，请在手机“已关联设备”核对' }
}
