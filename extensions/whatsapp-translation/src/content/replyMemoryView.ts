import { ACTION_LABEL, MEMORY_KIND, MEMORY_STATUS } from '@/shared/replyMemory'
import type { MemoryCommand, ReplyInquiry } from '@/shared/replyMemory'
import type { ReplyState } from '@/content/replyAssistant'

export type MemoryHandlers = {
  list: () => void; preview: (id: string) => void; usePreview: () => void
  create: (label: string) => void; enabled: (enabled: boolean) => void
  refresh: () => void; remove: () => void; save: () => void
  correct: (entryId: string, status: MemoryCommand['status'], note: string) => void
  pause: (paused: boolean) => void
}

export function createMemoryView(doc: Document, handlers: MemoryHandlers) {
  const root = doc.createElement('details')
  const summary = doc.createElement('summary'); summary.textContent = '询盘记录与承诺台账'
  const body = doc.createElement('div'); root.append(summary, body)
  const el = <K extends keyof HTMLElementTagNameMap>(tag: K, text = '') => {
    const node = doc.createElement(tag); node.textContent = text; return node
  }
  function button(text: string, action: () => void, disabled = false) {
    const node = el('button', text); node.type = 'button'; node.className = 'link'; node.disabled = disabled
    node.addEventListener('click', action); return node
  }
  function entries(record: ReplyInquiry, editable: boolean, disabled: boolean) {
    const section = el('div')
    section.append(el('p', `${record.label} · ${record.id.slice(0, 8)} · 版本 ${record.revision}`),
      el('p', `到期删除：${record.expires_at.replace('T', ' ').slice(0, 19)}（北京时间）`))
    if (!record.entries.length) section.append(el('p', '暂无复盘记录。'))
    for (const item of record.entries) {
      const detail = el('details')
      detail.append(el('summary', `${MEMORY_KIND[item.kind]} · ${MEMORY_STATUS[item.status]}：${item.status === 'human_confirmed' && item.human_note ? item.human_note : item.summary}`))
      for (const evidence of item.evidence) detail.append(el('p', `${evidence.role === 'customer' ? '客户' : '卖方'}原文摘录：${evidence.quote}`),
        el('small', `片段 ${evidence.request_id.slice(0, 8)} · 第 ${evidence.message_index + 1} 条 · ${evidence.observed_at.replace('T', ' ').slice(0, 19)}`))
      if (item.human_note) detail.append(el('p', `人工修正：${item.human_note}`))
      if (editable) {
        const status = el('select'); status.setAttribute('aria-label', `修正状态 ${item.id}`)
        const values: MemoryCommand['status'][] = item.kind === 'need' ? ['human_confirmed', 'cancelled'] : ['pending', 'human_completed', 'cancelled']
        for (const value of values) { const option = el('option', MEMORY_STATUS[value!]); option.value = value!; status.append(option) }
        const note = el('textarea'); note.maxLength = 240; note.placeholder = '填写核实后的内容或取消原因'; note.setAttribute('aria-label', `修正说明 ${item.id}`)
        const save = button('保存人工修正', () => { if (note.value.trim()) handlers.correct(item.id, status.value as MemoryCommand['status'], note.value) }, disabled)
        detail.append(status, note, save)
      }
      section.append(detail)
    }
    return section
  }
  return {
    root,
    render(state: ReplyState, errorText: (code: string) => string) {
      root.hidden = !state.capabilities?.memory_enabled
      body.replaceChildren()
      if (root.hidden) return
      const disabled = state.busy || !!state.memoryBusy
      const enableLabel = el('label'); const enable = el('input'); enable.type = 'checkbox'; enable.checked = state.memoryEnabled !== false
      enable.disabled = disabled; enable.addEventListener('change', () => handlers.enabled(enable.checked))
      enableLabel.append(enable, doc.createTextNode(' 保存询盘复盘'))
      body.append(enableLabel, el('p', `仅当前方舟账号和配对设备可访问。记录自创建起保留 ${state.capabilities?.memory_retention_days ?? 30} 天，可主动删除；不保存完整聊天、草稿或 WhatsApp 客户标识。切换聊天后不按姓名自动关联。`))
      if (state.memoryError) {
        const error = el('p', errorText(state.memoryError)); error.setAttribute('role', 'alert'); body.append(error)
        if (state.result && state.inquiry) body.append(button('重试保存复盘', handlers.save, disabled))
      }
      if (state.memoryNotice) body.append(el('p', state.memoryNotice))
      if (state.memoryBusy) body.append(el('p', '正在更新询盘记录…'))
      const actions = el('div'); actions.className = 'actions'
      actions.append(button('查找已有询盘', handlers.list, disabled))
      const label = el('input'); label.type = 'text'; label.maxLength = 80; label.placeholder = '新询盘备注（可选）'; label.setAttribute('aria-label', '新询盘备注')
      actions.append(label, button('新建独立记录', () => handlers.create(label.value), disabled))
      body.append(actions)
      if (state.inquiries) {
        if (!state.inquiries.length) body.append(el('p', '当前设备没有可恢复的询盘记录。'))
        for (const inquiry of state.inquiries) body.append(button(`${inquiry.label} · ${inquiry.id.slice(0, 8)} · ${inquiry.updated_at.replace('T', ' ').slice(0, 16)}`, () => handlers.preview(inquiry.id), disabled))
      }
      if (state.previewInquiry) {
        body.append(el('p', '请核对下列内容是否属于当前客户及本次采购事项。'), entries(state.previewInquiry, false, disabled),
          button('确认属于当前客户，使用这份记录', handlers.usePreview, disabled))
      }
      if (state.inquiry) {
        body.append(entries(state.inquiry, true, disabled), button('刷新记录', handlers.refresh, disabled))
        const removal = el('details'); removal.append(el('summary', '删除当前记录'),
          el('p', '删除后无法恢复；已生成的旧候选也不能将它写回。'), button('确认删除此记录', handlers.remove, disabled))
        body.append(removal)
      } else body.append(el('p', state.memoryEnabled === false ? '仅本次片段模式。' : '下次生成将新建记录；继续旧询盘请先选择已有记录。'))
    },
  }
}

export function renderHandoff(doc: Document, state: ReplyState, pause: (paused: boolean) => void) {
  const section = doc.createElement('details')
  const summary = doc.createElement('summary'); summary.textContent = '接管摘要（仅内部）'; section.append(summary)
  const append = (text: string) => { const p = doc.createElement('p'); p.textContent = text; section.append(p) }
  const result = state.result ?? state.handoffResult
  const handoff = result?.handoff
  if (handoff) {
    for (const need of handoff.needs) append(`需求：${need}`)
    for (const request of handoff.open_requests) append(`未回应：${request}`)
    for (const commitment of handoff.commitments) append(`承诺：${commitment.summary}（${MEMORY_STATUS[commitment.status as keyof typeof MEMORY_STATUS]}）`)
    append(`下一步：${handoff.next_step}`); append(`完成信号：${handoff.completion_signal}`); append(handoff.limitations)
  }
  if (result?.action) append(`建议动作：${ACTION_LABEL[result.action.kind]}。由${result.action.owner === 'salesperson' ? '业务员' : result.action.owner === 'customer' ? '客户' : '本轮无需行动'}完成。`)
  const button = doc.createElement('button'); button.type = 'button'; button.className = 'link'
  button.textContent = state.paused ? '恢复话术辅助' : '暂停生成，由我接管'; button.addEventListener('click', () => pause(!state.paused)); section.append(button)
  return section
}
