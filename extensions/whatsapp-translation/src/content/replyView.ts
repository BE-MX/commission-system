import { LANGUAGE_LABELS, TARGET_LANGUAGES, languageLabel } from '@/shared/contracts'
import type { ReplyStyle } from '@/shared/contracts'
import type { ReplyOptions, ReplyState } from '@/content/replyAssistant'
import { messageForCode } from '@/content/messages'
import { REPLY_RISK_LABELS } from '@/shared/replyCodes'

export const REPLY_COPY: Record<string, string> = {
  reply_busy: '已有话术正在生成，请稍后重试。', reply_in_progress: '本次话术仍在生成，请稍后重试。',
  reply_configuration_changed: '话术配置已更新，请重新生成。', reply_sources_changed: '知识依据已更新，请重新生成。',
  reply_configuration_invalid: '话术配置有误，请联系管理员检查。', reply_not_configured: '话术模型尚未配置，请联系管理员。',
  reply_not_enabled: '话术功能尚未启用，请联系管理员。', reply_permission_denied: '账号尚未开通话术权限，请联系管理员。',
  reply_context_too_large: '上下文超过服务限制，请改为最近 20 条后重试。',
  reply_daily_quota_exceeded: '今日话术额度已用完，请明日再试。', reply_rate_limited: '话术请求较快，请稍后重试。',
  reply_internal_disclosure: '话术可能包含内部信息，已拦截，请重新生成。',
  reply_invalid_evidence: '话术引用依据未通过校验，请重新生成。', reply_missing_evidence: '话术缺少事实依据，已拦截，请重新生成。',
  reply_unsupported_number: '话术包含未经确认的数值，已拦截，请重新生成。',
  reply_language_mismatch: '话术语言与所选语言不一致，请重新生成。', reply_unsafe_response: '话术包含未经确认的承诺或不适当内容，已拦截。',
  reply_invalid_request: '话术请求内容无效，请重新采集当前聊天后生成。',
  reply_request_conflict: '本次请求状态冲突，请重新生成。', reply_result_unavailable: '本次结果已不可用，请重新生成。',
  reply_timeout: '话术生成超时，请重试。', reply_disclosure_required: '请阅读数据去向说明后点击生成。',
  reply_stale: '聊天或输入已变化，请重新生成。', reply_cancelled: '已取消，本次结果不会显示。',
  reply_filled: '已填入输入框，请检查后自行发送。', reply_restored: '已恢复原草稿。',
  reply_unavailable: '当前服务尚未开放话术，请联系管理员。', reply_empty_context: '当前页面没有可用文本，请打开一对一聊天。',
  reply_latest_too_long: '最新一条文本超过当前服务字符上限，无法生成话术。',
  reply_draft_too_long: '草稿超过当前服务上限，请缩短或关闭“使用草稿意图”。',
  reply_goal_too_long: '本次目标超过当前服务字符上限，请缩短。', reply_invalid_response: '话术结果未通过校验，请重新生成。',
  reply_failed: '话术生成失败，请重试。', request_timeout: '话术生成超时，请重试。', ai_timeout: '话术生成超时，请重试。',
  ai_unavailable: '话术服务暂时不可用，请稍后重试。',
}
export function createReplyView(shadow: ShadowRoot, handlers: {
  generate: (options: ReplyOptions, style: ReplyStyle) => void
  change: () => void; close: () => void; cancel: () => void; fill: () => void; restore: () => void
}) {
  const doc = shadow.ownerDocument
  const root = doc.createElement('section')
  root.className = 'ark reply-panel'
  root.hidden = true
  root.setAttribute('aria-label', '话术助手')
  const style = doc.createElement('style')
  style.textContent = `.reply-panel { padding-bottom:8px; } .reply-panel[hidden] { display:none; }
    .reply-panel .card { max-height: min(460px, 55vh); overflow:auto; }
    .reply-panel .actions { flex-wrap:wrap; } .reply-panel .text { overflow-wrap:anywhere; }
    .reply-panel textarea { background:var(--surface); color:var(--fg); border:1px solid var(--border); border-radius:8px; width:100%; min-height:54px; resize:vertical; font:inherit; padding:8px; }
    .reply-panel select { background:var(--surface); color:var(--fg); font:inherit; border:1px solid var(--border); border-radius:8px; padding:4px; }
    .reply-panel summary { cursor:pointer; color:var(--muted); margin-top:8px; } .reply-panel p { margin:8px 0; }
    .reply-panel button:focus-visible, .reply-panel select:focus-visible, .reply-panel textarea:focus-visible { outline:2px solid var(--link); outline-offset:2px; }
    .reply-panel .disclosure { color:var(--muted); } .reply-panel .primary { font-size:15px; }
    .reply-panel .status { margin:8px 0; display:block; }`
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') => {
    const node = doc.createElement(tag); node.textContent = text; node.className = className; return node
  }
  function button(label: string, action: () => void, primary = false) {
    const node = el('button', label, primary ? 'btn' : 'link'); node.type = 'button'; node.addEventListener('click', action); return node
  }
  root.addEventListener('mousedown', e => { if (e.button === 0 && (e.target as Element).closest('button')) e.preventDefault() })
  root.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); handlers.close() } })
  const card = el('div', '', 'card')
  const head = el('div', '', 'actions')
  head.append(el('strong', '话术助手'), button('关闭话术', handlers.close))
  const disclosure = el('p', '仅使用当前已加载的聊天文本；文本和可选草稿意图将发送至莱莎方舟及已配置模型。仅预览和填入，绝不自动发送。', 'disclosure')
  const settings = el('div', '', 'actions')
  const limit = el('select'); limit.setAttribute('aria-label', '话术上下文条数')
  const defaultLimit = el('option', '默认最近 20 条'); defaultLimit.value = 'default'; limit.append(defaultLimit)
  for (const n of [20, 40]) { const o = el('option', `最近 ${n} 条`); o.value = String(n); limit.append(o) }
  const language = el('select'); language.setAttribute('aria-label', '话术语言')
  for (const code of ['auto', ...TARGET_LANGUAGES]) { const o = el('option', code === 'auto' ? '自动判断客户语言' : LANGUAGE_LABELS[code]); o.value = code; language.append(o) }
  const draftLabel = el('label'); const include = el('input'); include.type = 'checkbox'; include.checked = true
  draftLabel.append(include, doc.createTextNode(' 使用草稿意图'))
  settings.append(limit, language, draftLabel)
  const goal = el('textarea'); goal.maxLength = 500; goal.placeholder = '本次目标（可选，最多 500 字符）'; goal.setAttribute('aria-label', '本次目标')
  const options = (): ReplyOptions => ({ limit: limit.value === 'default' ? 'default' : Number(limit.value) as 20 | 40, language: language.value as ReplyOptions['language'], includeDraft: include.checked, goal: goal.value })
  for (const input of [limit, language, include]) input.addEventListener('change', handlers.change)
  goal.addEventListener('input', handlers.change)
  const snapshot = el('p', '', 'text back'); const status = el('p', '', 'status'); status.setAttribute('role', 'status')
  const output = el('div'); const actions = el('div', '', 'actions')
  const generate = button('生成话术', () => handlers.generate(options(), 'default'), true)
  const cancel = button('取消生成', handlers.cancel)
  actions.append(generate, cancel)
  card.append(head, disclosure, settings, goal, actions, snapshot, status, output)
  root.append(card); shadow.append(style, root)
  return {
    options,
    render(state: ReplyState) {
      root.hidden = !state.open
      if (state.capabilities) {
        const caps = state.capabilities
        defaultLimit.textContent = `默认最近 ${caps.default_messages} 条`
        goal.maxLength = caps.max_goal_chars
        goal.placeholder = `本次目标（可选，最多 ${caps.max_goal_chars} 字符）`
        draftLabel.title = `草稿意图最多 ${caps.max_draft_chars} 字符`
      }
      generate.disabled = state.busy
      generate.textContent = state.busy ? '生成中…' : '重新生成话术'
      cancel.hidden = !state.busy
      status.textContent = state.error ? (REPLY_COPY[state.error] ?? messageForCode(state.error).text) : state.busy ? '正在生成，可继续查看聊天；编辑草稿会使本次生成失效。' : ''
      const context = state.context
      snapshot.textContent = context ? `使用 ${context.messages.length} 条 · ${context.range} · 当前已加载 ${context.loadedCount} 条可用文本。上限 ${state.capabilities?.max_context_chars ?? 12000} 字符 / ${state.capabilities?.max_messages ?? 40} 条。${context.context_scope.truncated ? '已按条数或字符上限截断。' : ''}${context.context_scope.omitted_media ? '已跳过媒体，存在上下文缺口。' : ''}${context.skippedUnknown ? '已跳过无法识别的消息。' : ''}无法确认是否包含最新消息。` : ''
      output.replaceChildren()
      if (state.canRestore) output.append(button('恢复原草稿', handlers.restore))
      const result = state.result
      if (!result) return
      output.append(el('p', `建议回复 · ${languageLabel(result.reply_language)}`, 'label'), el('div', result.reply_text, 'text primary'))
      if (result.status !== 'ready') output.append(el('p', result.status === 'needs_confirmation' ? '需要补充确认，暂不可填入。' : '上下文不足，暂不可填入。', 'status'))
      const details = el('details'); details.append(el('summary', '中文含义、建议理由与依据'))
      details.append(el('p', result.meaning_zh, 'text'), el('p', result.rationale_zh, 'text'))
      for (const source of result.sources) details.append(el('p', `来源：${source.title} · v${source.version_no} · ${source.section}`, 'text back'))
      for (const missing of result.missing_information) details.append(el('p', `待确认：${missing}`, 'text'))
      for (const risk of result.risk_flags) details.append(el('p', `注意：${REPLY_RISK_LABELS[risk] ?? '请核实这条建议的适用条件'}`, 'text'))
      output.append(details)
      const resultActions = el('div', '', 'actions')
      if (result.status === 'ready') resultActions.append(button('填入输入框', handlers.fill, true))
      for (const [label, value] of [['短一点', 'shorter'], ['柔和一点', 'softer'], ['换个策略', 'alternative']] as const) resultActions.append(button(label, () => handlers.generate(options(), value)))
      resultActions.append(button('按本次目标生成', () => handlers.generate(options(), 'default')))
      output.append(resultActions)
    },
  }
}
