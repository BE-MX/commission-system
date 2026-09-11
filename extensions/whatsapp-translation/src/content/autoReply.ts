import { REPLY_COPY } from '@/content/replyView'
import { messageForCode } from '@/content/messages'
import type { ReplyCapabilities, ReplyRequest, ReplyResponse, TargetLanguage } from '@/shared/contracts'
import { maskContacts } from '@/whatsapp/replyContext'
import type { ReplyContext } from '@/whatsapp/replyContext'
import { boundedReplyCapabilities, validReplyResponse } from '@/shared/replyValidation'

export type AutoSnapshot = { identity: unknown[]; tail: string; incoming: string; role?: string; draft: string }
export type AutoState = { active: boolean; busy: boolean; note: string }
export function createAutoReply(adapter: {
  snapshot: () => AutoSnapshot
  collect: (caps: ReplyCapabilities, current: () => boolean) => Promise<ReplyContext>
  send: (text: string, current: () => boolean) => Promise<boolean>
}, bridge: { capabilities: () => Promise<unknown>; suggest: (request: ReplyRequest) => Promise<ReplyResponse> },
options: () => { language: 'auto' | TargetLanguage; fallback: TargetLanguage; goal: string }, changed: (state: AutoState) => void,
wait = (ms: number) => new Promise<void>(resolve => setTimeout(resolve, ms))) {
  let state: AutoState = { active: false, busy: false, note: '' }
  let collecting = false
  let revision = 0, timer: ReturnType<typeof setInterval> | undefined
  let identity: unknown[] = [], incoming = '', settledAt = 0, processed = '', epoch = ''
  const paint = () => changed({ ...state })
  const sameChat = (snapshot: AutoSnapshot) => identity.every((v, i) => snapshot.identity[i] === v)
  function stop(note = '自动接管已关闭') {
    revision++; state.active = false; state.note = note
    if (timer) clearInterval(timer); timer = undefined; paint()
  }
  async function run() {
    if (!state.active || state.busy || Date.now() - settledAt < 3000 || incoming === processed) return
    state.busy = true; state.note = '正在生成回复…'; paint()
    const version = revision
    const current = () => state.active && revision === version && sameChat(adapter.snapshot())
      && (collecting || adapter.snapshot().incoming === incoming)
    try {
      const caps = boundedReplyCapabilities(await bridge.capabilities())
      if (!caps.auto_reply_enabled) throw new Error('后端尚未支持自动接管，请更新后端')
      if (!current()) return
      collecting = true
      const context = await adapter.collect(caps, current)
      collecting = false
      if (!current()) return
      if (!context.context_scope.latest_visible || context.context_scope.truncated || context.skippedUnknown || !context.messages.length) throw new Error('聊天内容不完整，请人工确认')
      const latest = context.messages.at(-1)!
      if (latest.role !== 'customer') { processed = incoming; state.note = '等待客户新消息'; return }
      if (latest.kind === 'media' || latest.kind === 'unknown') throw new Error('最新消息含未读取内容，请人工接管')
      const selected = options()
      const request: ReplyRequest = {
        mode: 'auto', request_id: crypto.randomUUID(), conversation_epoch: epoch,
        context_version: version, draft_version: 0, messages: context.messages, context_scope: context.context_scope,
        draft_intent: '', target_language: selected.language, fallback_language: selected.fallback, goal: maskContacts(selected.goal), style: 'default',
      }
      const observed = adapter.snapshot()
      if (observed.role !== 'customer') { processed = incoming; state.note = '检测到卖方已回复，等待客户新消息'; return }
      let tail = observed.tail
      const response = await bridge.suggest(request)
      if (!current()) return
      if (!validReplyResponse(response, request) || response.status !== 'ready') throw new Error('回复格式异常，已停止接管')
      if (response.auto_action === 'handoff') { stop('需要人工处理：' + response.rationale_zh); return }
      if (response.auto_action === 'wait') { processed = incoming; state.note = '本轮无需回复，等待客户新消息'; return }
      for (const [index, part] of response.reply_segments!.entries()) {
        state.note = `准备发送第 ${index + 1}/${response.reply_segments!.length} 段`; paint()
        await wait(index ? 2500 : 1500)
        if (!current()) return
        const snapshot = adapter.snapshot()
        if (snapshot.draft || snapshot.tail !== tail) throw new Error('聊天或输入已变化，请人工接管')
        if (!await adapter.send(part, current)) {
          if (state.active && sameChat(adapter.snapshot())) stop('发送结果未确认，已停止；请检查聊天记录，勿直接重发')
          return
        }
        tail = adapter.snapshot().tail
      }
      processed = incoming; state.note = '已回复，等待客户新消息'
    } catch (error) {
      if (state.active && revision === version) {
        const code = error instanceof Error ? error.message : ''
        stop(REPLY_COPY[code] ?? (/^[a-z_]+$/.test(code) ? messageForCode(code).text : code || '自动接管异常，已停止'))
      }
    } finally { collecting = false; state.busy = false; paint() }
  }
  function tick() {
    if (!state.active) return
    const snapshot = adapter.snapshot()
    if (!sameChat(snapshot)) { stop('聊天已切换，自动接管已关闭'); return }
    if (collecting) return
    if (snapshot.incoming !== incoming) { incoming = snapshot.incoming; revision++; settledAt = Date.now() }
    if (snapshot.draft && !state.busy) { stop('检测到人工草稿，自动接管已关闭'); return }
    if (!state.busy && snapshot.role === 'salesperson') { processed = incoming; return }
    void run()
  }
  return {
    getState: () => ({ ...state }), stop,
    start() {
      if (state.active || state.busy) return
      const snapshot = adapter.snapshot()
      if (snapshot.draft) { stop('请先处理输入框草稿，再开启自动接管'); return }
      identity = snapshot.identity; incoming = snapshot.incoming; processed = ''; epoch = crypto.randomUUID(); revision++
      settledAt = Date.now(); state = { active: true, busy: false, note: '已开启，仅当前聊天自动回复；可随时关闭' }; paint()
      timer = setInterval(tick, 1000)
    },
  }
}
