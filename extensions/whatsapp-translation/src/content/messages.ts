/** Stable error code -> what the employee sees and whether retry makes sense. */

export type UserMessage = {
  retryable: boolean
  text: string
}

const MESSAGES: Record<string, UserMessage> = {
  ai_timeout: { retryable: true, text: '翻译服务响应超时，点击重试' },
  ai_unavailable: { retryable: true, text: '翻译服务暂时不可用，点击重试' },
  chat_unsupported: { retryable: false, text: '仅支持一对一聊天' },
  composer_changed: { retryable: true, text: '输入内容已变化，请重新翻译' },
  daily_quota_exceeded: { retryable: false, text: '今日翻译额度已用完，明日恢复' },
  device_expired: { retryable: false, text: '授权已过期，请在扩展弹窗重新授权' },
  device_not_found: { retryable: false, text: '授权已失效，请在扩展弹窗重新授权' },
  device_revoked: { retryable: false, text: '设备已被撤销，请在扩展弹窗重新授权' },
  device_token_missing: { retryable: false, text: '尚未授权，请点击扩展图标登录方舟' },
  empty_composer: { retryable: false, text: '输入框为空' },
  extension_outdated: { retryable: false, text: '扩展版本过低，请更新后继续使用' },
  invalid_bearer: { retryable: false, text: '授权已失效，请在扩展弹窗重新授权' },
  network_error: { retryable: true, text: '连接方舟失败，点击重试' },
  permission_denied: { retryable: false, text: '账号暂无 WhatsApp 翻译权限' },
  rate_limited: { retryable: true, text: '请求较快，稍后自动恢复' },
  request_timeout: { retryable: true, text: '连接方舟超时，点击重试' },
  text_too_long: { retryable: false, text: '单条超过 4000 字，请拆开发送' },
  translation_disabled: { retryable: false, text: '翻译已在扩展弹窗中关闭' },
  translation_invalid_response: { retryable: true, text: '翻译结果无效，点击重试' },
  unsupported_language: { retryable: false, text: '不支持的目标语言' },
  user_inactive: { retryable: false, text: '账号已停用' },
}

const FALLBACK: UserMessage = { retryable: true, text: '翻译失败，点击重试' }

export function messageForCode(code: string | undefined): UserMessage {
  return (code && MESSAGES[code]) || FALLBACK
}

export function codeFromError(error: unknown): string {
  if (error && typeof error === 'object' && 'code' in error && typeof (error as { code: unknown }).code === 'string') {
    return (error as { code: string }).code
  }
  if (error instanceof Error) return error.message
  return 'unexpected_error'
}
