import { createAdminCommand } from './command.mjs'

export const deliveryStatuses = { pending: '等待投递', sending: '正在处理', expanded: '已分发子任务', sent: '已发送', cancelled: '已取消', expired: '已过期', dead: '投递停止' }
export const notificationEvents = { order_submitted: '客户提交请求', order_cancelled: '客户取消请求', order_accepted: '客户接受提案', order_proposal_rejected: '客户拒绝提案', pi_accepted: '客户接受 PI 修改', pi_rejected: '客户拒绝 PI 修改', order_proposed: '发送提案', order_rejected: '拒绝请求', order_invoice_created: '生成 PI', pi_proposed: '发送 PI 修改提案', pi_published: '发布 PI', order_pi_voided: '作废 PI', business_mail: '邮件投递', mapping_published: '映射发布', mapping_mail: '映射更新邮件' }
export const notificationErrors = { MAIL_TRANSPORT_FAILED: '邮件服务暂时失败', AUTHORITY_UNAVAILABLE: '授权服务暂不可用', NOTIFICATION_CONFIGURATION_INVALID: '通知配置需要检查', LEASE_EXPIRED_BEFORE_SEND: '发送前租约过期', ATTEMPTS_EXHAUSTED: '已达到尝试次数上限', AUTHORIZATION_CHANGED: '当前授权已变化', NO_ACTIVE_RECIPIENT: '没有有效收件人', NOTIFICATION_SOURCE_INVALID: '来源事件需要核对', NOTIFICATION_RECIPIENT_INVALID: '收件人配置需要核对', NOTIFICATION_OBJECT_INVALID: '对象已不可用', NOTIFICATION_SUPERSEDED: '已被更新的映射替换' }

export function createNotificationCommand(send, { scope = 'order' } = {}) {
  const receiptField = scope === 'mapping' ? 'access_id' : scope === 'order' ? 'request_id' : null
  if (!receiptField) throw new Error('无效通知对象类型。')
  return createAdminCommand(async command => {
    const result = await send(command), receipt = result?.original_receipt
    if (typeof result?.replayed !== 'boolean' || receipt?.[receiptField] !== command.id || receipt?.event_id !== command.eventId || receipt?.command_key !== command.key || receipt?.status !== 'pending' || result?.current?.id !== command.eventId || !Object.hasOwn(deliveryStatuses, result?.current?.status)) {
      const error = new Error('未收到匹配的重试回执，请核对原命令。')
      error.uncertain = true
      throw error
    }
    return { ...result, current_state: result.current.status }
  }, { receiptField })
}
