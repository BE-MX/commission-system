import { REPLY_PANEL_STYLES } from '@/content/replyViewStyles'
import { LANGUAGE_LABELS, TARGET_LANGUAGES, languageLabel } from '@/shared/contracts'
import type { ReplyStyle } from '@/shared/contracts'
import type { ReplyOptions, ReplyState } from '@/content/replyAssistant'
import { messageForCode } from '@/content/messages'
import { REPLY_RISK_LABELS } from '@/shared/replyCodes'
import { createMemoryView, renderHandoff } from '@/content/replyMemoryView'
import type { MemoryHandlers } from '@/content/replyMemoryView'

export const REPLY_COPY: Record<string, string> = {
  reply_memory_disabled: '当前服务未启用询盘记录。', reply_memory_not_found: '记录不存在、已到期或不属于当前账号和设备。',
  reply_memory_conflict: '记录已被其他操作更新，请刷新记录后重新生成。', reply_memory_full: '记录容量已满，请整理记录或新建独立询盘。',
  reply_memory_human_override: '复盘试图覆盖人工修正，已拦截，请核对后重新生成。',
  reply_repeated_question: '检测到重复询问已回答的问题，已拦截，请重新生成。', reply_paused: '已由业务员接管，请先恢复话术辅助。',
  reply_busy: '已有话术正在生成，请稍后重试。', reply_in_progress: '本次话术仍在生成，请稍后重试。',
  reply_configuration_changed: '话术配置已更新，请重新生成。', reply_sources_changed: '知识依据已更新，请重新生成。',
  reply_configuration_invalid: '话术配置有误，请联系管理员检查。', reply_not_configured: '话术模型尚未配置，请联系管理员。',
  reply_not_enabled: '话术功能尚未启用，请联系管理员。', reply_permission_denied: '账号尚未开通话术权限，请联系管理员。',
  reply_context_too_large: '已采集内容超过本次服务容量，尚未发送。可下载 JSON，或明确选择较小范围。',
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
  reply_backend_update_required: '当前后端尚未支持长历史话术，请先更新后端。',
  reply_history_busy: '上次历史采集正在结束，请稍后重试。',
  reply_history_changed: '聊天身份或历史连续性无法确认，已停止采集，请在原聊天重试。',
  reply_send_control_unavailable: '回复已填入，但发送按钮尚不可用，未点击发送；请检查输入框并手动发送。',
  reply_memory_update_failed: '复盘未保存，建议回复仍可使用。',
  reply_failed: '话术生成失败，请重试。', request_timeout: '话术生成超时，请重试。', ai_timeout: '话术生成超时，请重试。',
  ai_unavailable: '话术服务暂时不可用，请稍后重试。',
}
export function createReplyView(shadow: ShadowRoot, handlers: {
  generate: (options: ReplyOptions, style: ReplyStyle) => void
  change: () => void; close: () => void; cancel: () => void; fill: () => void; restore: () => void
  memory?: MemoryHandlers
}) {
  const doc = shadow.ownerDocument
  const root = doc.createElement('section')
  root.className = 'ark reply-panel'
  root.hidden = true
  root.setAttribute('aria-label', '话术助手')
  const style = doc.createElement('style')
  style.textContent = REPLY_PANEL_STYLES
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '', className = '') => {
    const node = doc.createElement(tag); node.textContent = text; node.className = className; return node
  }
  function button(label: string, action: () => void, primary = false) {
    const node = el('button', label, primary ? 'btn' : 'link'); node.type = 'button'; node.addEventListener('click', action); return node
  }
  root.addEventListener('mousedown', e => { if (e.button === 0 && (e.target as Element).closest('button')) e.preventDefault() })
  root.addEventListener('keydown', e => { if (e.key === 'Escape') { e.stopPropagation(); handlers.close() } })
  const card = el('div', '', 'card')
  const head = el('div', '', 'reply-head')
  head.append(el('strong', '话术助手'), button('关闭话术', handlers.close))
  const disclosure = el('p', '当前聊天可获取历史、可选草稿意图及所选询盘复盘将发送至莱莎方舟及已配置模型。启用记录时保存有来源的需求和待办，不保存草稿为已发送消息。仅预览和填入，不自动发送。', 'disclosure')
  const settings = el('div', '', 'reply-settings')
  const limit = el('select'); limit.setAttribute('aria-label', '话术上下文条数')
  const defaultLimit = el('option', '加载历史并生成'); defaultLimit.value = 'default'; limit.append(defaultLimit)
  const loaded = el('option', '仅当前已加载消息'); loaded.value = 'loaded'; limit.append(loaded)
  for (const n of [20, 40]) { const o = el('option', `最近 ${n} 条`); o.value = String(n); limit.append(o) }
  const language = el('select'); language.setAttribute('aria-label', '话术语言')
  for (const code of ['auto', ...TARGET_LANGUAGES]) { const o = el('option', code === 'auto' ? '自动判断客户语言' : LANGUAGE_LABELS[code]); o.value = code; language.append(o) }
  const draftLabel = el('label'); const include = el('input'); include.type = 'checkbox'; include.checked = true
  draftLabel.append(include, doc.createTextNode(' 使用草稿意图'))
  settings.append(language, draftLabel)
  const goal = el('textarea'); goal.maxLength = 500; goal.placeholder = '本次目标（可选，最多 500 字符）'; goal.setAttribute('aria-label', '本次目标')
  const options = (): ReplyOptions => ({ limit: ['default', 'loaded'].includes(limit.value) ? limit.value as 'default' | 'loaded' : Number(limit.value) as 20 | 40, language: language.value as ReplyOptions['language'], includeDraft: include.checked, goal: goal.value })
  for (const input of [limit, language, include]) input.addEventListener('change', handlers.change)
  goal.addEventListener('input', handlers.change)
  const snapshot = el('p', '', 'text back'); const status = el('p', '', 'status'); status.setAttribute('role', 'status')
  const output = el('div'); const actions = el('div', '', 'actions')
  const generate = button('生成话术', () => handlers.generate(options(), 'default'), true)
  const cancel = button('取消生成', handlers.cancel)
  const fillSlot = el('div', '', 'actions')
  actions.classList.add('reply-footer')
  actions.append(fillSlot, generate, cancel)
  const memoryView = handlers.memory ? createMemoryView(doc, handlers.memory) : undefined
  const tabs = el('div', '', 'reply-tabs'); tabs.setAttribute('role', 'tablist'); tabs.setAttribute('aria-label', '话术内容')
  const replyPane = el('div', '', 'reply-pane')
  const contextPane = el('div', '', 'reply-pane')
  const memoryPane = el('div', '', 'reply-pane')
  const panels = [replyPane, contextPane, memoryPane]
  const tabButtons: HTMLButtonElement[] = []
  function selectTab(index: number) {
    panels.forEach((panel, i) => { panel.hidden = i !== index; tabButtons[i].setAttribute('aria-selected', String(i === index)); tabButtons[i].tabIndex = i === index ? 0 : -1 })
  }
  for (const [index, label] of ['建议回复', '聊天上下文', '询盘与接管'].entries()) {
    const tab = button(label, () => selectTab(index)); tab.setAttribute('role', 'tab')
    tab.id = `reply-tab-${index}`; tab.setAttribute('aria-controls', `reply-pane-${index}`)
    const panel = panels[index]; panel.id = `reply-pane-${index}`; panel.setAttribute('role', 'tabpanel'); panel.setAttribute('aria-labelledby', tab.id)
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
      event.preventDefault()
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? 2 : (index + (event.key === 'ArrowRight' ? 1 : 2)) % 3
      selectTab(next); tabButtons[next].focus()
    })
    tabButtons.push(tab); tabs.append(tab)
  }
  selectTab(0)
  const preferences = el('details', '', 'reply-preferences'); preferences.append(el('summary', '调整生成要求'), settings, goal)
  const brief = el('p', '聊天内容发送至方舟及配置模型，仅生成草稿，由你确认发送。', 'reply-caption')
  replyPane.append(brief, output, preferences)
  const exportSlot = el('div', '', 'actions')
  const scopeLabel = el('label', '读取范围', 'reply-field'); scopeLabel.append(limit)
  const privacy = el('details'); privacy.append(el('summary', '数据使用说明'), disclosure)
  contextPane.append(el('h3', '本次聊天记录'), scopeLabel, snapshot, exportSlot, privacy)
  const memoryEmpty = el('p', '生成回复后可查看接管摘要；询盘记录需管理员启用。', 'reply-caption')
  const handoffSlot = el('div')
  memoryPane.append(memoryEmpty, handoffSlot)
  if (memoryView) { memoryView.root.open = true; memoryPane.append(memoryView.root) }
  else memoryPane.append(el('p', '当前未启用询盘记录。', 'reply-caption'))
  card.append(head, tabs, status, ...panels, actions)
  root.append(card); shadow.append(style, root)
  return {
    options,
    render(state: ReplyState) {
      root.hidden = !state.open
      if (state.capabilities) {
        const caps = state.capabilities
        defaultLimit.textContent = '加载历史并生成'
        goal.maxLength = caps.max_goal_chars
        goal.placeholder = `本次目标（可选，最多 ${caps.max_goal_chars} 字符）`
        draftLabel.title = `草稿意图最多 ${caps.max_draft_chars} 字符`
      }
      generate.disabled = !!state.collecting || state.busy || !!state.memoryBusy || !!state.paused
      generate.textContent = state.collecting ? '加载历史中…' : state.busy ? '生成中…' : '重新生成话术'
      generate.className = state.result?.status === 'ready' ? 'link' : 'btn'
      cancel.hidden = !state.busy
      status.textContent = state.error ? (REPLY_COPY[state.error] ?? messageForCode(state.error).text) : state.collecting ? '正在向上加载并累计历史，可取消；切换聊天会停止采集。' : state.busy ? '正在生成，长历史会分段整理；编辑草稿会使本次生成失效。' : ''
      status.hidden = !status.textContent
      const context = state.context
      snapshot.textContent = context ? `已采集 ${context.messages.length} 条 · ${context.range}。${context.context_scope.truncated ? '超过容量，未发送。' : ''}${context.context_scope.omitted_media ? '媒体仅保留占位，内容未读取。' : ''}${context.skippedUnknown ? '存在无法识别的消息。' : ''}${context.context_scope.history_status === 'web_boundary_unverified' ? '已滚动至网页当前边界，不能保证包含手机全部历史。' : '仅代表已采集范围，完整性未确认。'}` : ''

      output.replaceChildren(); exportSlot.replaceChildren(); fillSlot.replaceChildren(); handoffSlot.replaceChildren()
      if (context?.messages.length) exportSlot.append(button('下载聊天 JSON', () => {
        const blob = new Blob([JSON.stringify({ schema_version: 1, context_scope: context.context_scope, messages: context.messages }, null, 2)], { type: 'application/json' })
        const url = URL.createObjectURL(blob)
        const link = doc.createElement('a'); link.href = url; link.download = 'whatsapp-conversation.json'; link.click()
        setTimeout(() => URL.revokeObjectURL(url), 1000)
      }))
      if (state.canRestore) fillSlot.append(button('恢复原草稿', handlers.restore))
      memoryEmpty.hidden = !!state.capabilities?.memory_enabled || !!state.result?.handoff || !!state.handoffResult
      const result = state.result
      memoryView?.render(state, code => REPLY_COPY[code] ?? '询盘记录操作失败，请重试。')
      if (state.paused && handlers.memory) handoffSlot.append(renderHandoff(doc, state, handlers.memory.pause))
      if (!result) { output.append(el('p', state.busy ? '正在准备建议回复…' : state.paused ? '已暂停辅助，可在「询盘与接管」中恢复。' : '生成一条回复，核对后填入聊天框。', 'reply-empty')); return }
      if (result.context_processing === 'summarized') exportSlot.append(el('p', '本次历史较长，已分段整理后生成；下载 JSON 可查看原始采集内容。'))
      output.append(el('p', `建议回复 · ${languageLabel(result.reply_language)}`, 'label'), el('div', result.reply_text, 'text reply-draft'))
      if (result.status !== 'ready') output.append(el('p', result.status === 'needs_confirmation' ? '需要补充确认，暂不可填入。' : '上下文不足，暂不可填入。', 'status'))
      output.append(el('p', result.meaning_zh, 'text reply-meaning'))
      const details = el('details'); details.append(el('summary', '建议理由与依据'))
      details.append(el('p', result.rationale_zh, 'text'))
      for (const source of result.sources) details.append(el('p', `来源：${source.title} · v${source.version_no} · ${source.section}`, 'text back'))
      for (const missing of result.missing_information) details.append(el('p', `待确认：${missing}`, 'text'))
      for (const risk of result.risk_flags) details.append(el('p', `注意：${REPLY_RISK_LABELS[risk] ?? '请核实这条建议的适用条件'}`, 'text'))
      output.append(details)
      if (result.materials?.length) {
        const materials = el('details'); materials.append(el('summary', '可对客资料片段（请核对适用范围后使用）'))
        for (const material of result.materials) materials.append(el('p', material.title), el('p', material.applicability, 'text back'), el('p', material.text, 'text'))
        output.append(materials)
      }
      if (handlers.memory && result.handoff) handoffSlot.append(renderHandoff(doc, state, handlers.memory.pause))
      const resultActions = el('div', '', 'actions')
      if (result.status === 'ready') fillSlot.prepend(button('填入输入框', handlers.fill, true))
      for (const [label, value] of [['短一点', 'shorter'], ['柔和一点', 'softer'], ['换个策略', 'alternative']] as const) resultActions.append(button(label, () => handlers.generate(options(), value)))
      output.append(resultActions)
    },
  }
}
