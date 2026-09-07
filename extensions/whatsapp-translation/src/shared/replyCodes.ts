export const REPLY_ERROR_CODES = [
  'reply_busy', 'reply_configuration_changed', 'reply_configuration_invalid', 'reply_context_too_large',
  'reply_daily_quota_exceeded', 'reply_in_progress', 'reply_internal_disclosure', 'reply_invalid_evidence',
  'reply_invalid_request', 'reply_invalid_response', 'reply_language_mismatch', 'reply_missing_evidence',
  'reply_not_configured', 'reply_not_enabled', 'reply_permission_denied', 'reply_rate_limited',
  'reply_request_conflict', 'reply_result_unavailable', 'reply_sources_changed', 'reply_timeout',
  'reply_unavailable', 'reply_unsafe_response', 'reply_unsupported_number',
] as const
export const REPLY_RISK_LABELS: Record<string, string> = {
  limited_context: '仅依据有限的已加载上下文', media_not_read: '未读取图片、语音等媒体内容',
  language_uncertain: '客户语言尚不确定，请检查或手动选择', knowledge_unavailable: '未取得可用知识依据',
  policy_confirmation_required: '涉及业务政策，须先确认', conflicting_evidence: '参考依据存在冲突',
  historical_commitment: '历史聊天中存在承诺，须核实当前是否有效', internal_confirmation_required: '需要内部确认',
  alternative_not_supported: '暂无足够依据支持其他策略', no_public_facts: '没有可对外引用的产品事实',
}
