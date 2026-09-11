import { collectReplyContext, MESSAGE_IDENTITY } from './replyContext'
import type { ReplyContext, ReplyContextLimits } from './replyContext'
import { WHATSAPP_SELECTORS } from './selectors'

type Message = ReplyContext['messages'][number]
const key = (m: Message) => ((m as Message & { [MESSAGE_IDENTITY]?: string })[MESSAGE_IDENTITY] ?? '') + JSON.stringify(m)

/** Match whole overlapping windows; equal messages within a window stay distinct. */
export function mergeHistory(history: Message[], batch: Message[], direction: 'up' | 'down'): Message[] {
  if (!history.length) return batch
  const left = direction === 'up' ? batch : history
  const right = direction === 'up' ? history : batch
  for (let count = Math.min(left.length, right.length); count > 0; count--) {
    if (left.slice(-count).every((m, i) => key(m) === key(right[i]))) return [...left, ...right.slice(count)]
  }
  // A shorter DOM window wholly inside the accumulated history is not a gap.
  if (batch.length && history.some((_, i) => batch.every((m, j) => history[i + j] && key(m) === key(history[i + j])))) return history
  throw new Error('reply_history_changed')
}

export async function collectHistory(root: Document | HTMLElement, limits: ReplyContextLimits, current: () => boolean,
  progress: (context: ReplyContext) => void, wait = () => new Promise<void>(resolve => setTimeout(resolve, 450))): Promise<ReplyContext> {
  const chat = root.querySelector(WHATSAPP_SELECTORS.chatRoot)
  const header = root.querySelector(WHATSAPP_SELECTORS.conversationTitle)
  const title = header?.textContent
  const composer = root.querySelector(WHATSAPP_SELECTORS.composer)
  const sameChat = () => chat?.isConnected && root.querySelector(WHATSAPP_SELECTORS.chatRoot) === chat
    && root.querySelector(WHATSAPP_SELECTORS.conversationTitle) === header && header?.textContent === title
    && root.querySelector(WHATSAPP_SELECTORS.composer) === composer
  const check = () => { if (!current() || !sameChat()) throw new Error('reply_history_changed') }
  const read = () => collectReplyContext(root, 2000, { maxMessages: 2000, maxChars: 120000 })
  let context = read()
  let scroller = root.querySelector(WHATSAPP_SELECTORS.message)?.parentElement
  while (scroller && scroller !== chat && !(scroller.scrollHeight > scroller.clientHeight && /auto|scroll/.test(getComputedStyle(scroller).overflowY))) scroller = scroller.parentElement
  if (!scroller || scroller === chat) return { ...context, context_scope: { ...context.context_scope, history_status: 'loaded_only' } }
  const scroll = scroller
  const originalTop = scroll.scrollTop
  const originalHeight = scroll.scrollHeight
  const wasBottom = scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight < 5
  const originalRows = [...root.querySelectorAll(WHATSAPP_SELECTORS.message)]
  const anchor = originalRows.find(row => row.getBoundingClientRect().bottom > scroll.getBoundingClientRect().top)
  const anchorOffset = anchor ? anchor.getBoundingClientRect().top - scroll.getBoundingClientRect().top : 0
  let messages = context.messages
  let status = 'stalled'
  let safeToRestore = true
  const publish = () => {
    context = { ...context, messages, loadedCount: messages.length, range: `${messages[0]?.timestamp || '起始时间未知'} — ${messages.at(-1)?.timestamp || '结束时间未知'}`,
      context_scope: { ...context.context_scope, requested_limit: 2000, history_status: status, truncated: status === 'capacity' } }
    progress(context)
  }
  try {
    // First include the latest messages, then walk backwards with window overlap.
    for (const direction of ['down', 'up'] as const) {
      let idle = 0
      for (let step = 0; step < 240; step++) {
        check()
        scroll.scrollTop += (direction === 'up' ? -1 : 1) * Math.max(40, scroll.clientHeight * 0.5)
        await wait(); check()
        const batch = read()
        const before = messages.length
        try { messages = mergeHistory(messages, batch.messages, direction) }
        catch (error) { safeToRestore = false; throw error }
        context.context_scope.omitted_media ||= batch.context_scope.omitted_media
        context.skippedUnknown ||= batch.skippedUnknown
        if (batch.context_scope.truncated || messages.length > limits.maxMessages || messages.reduce((n, m) => n + m.text.length + (m.quoted_text?.length ?? 0), 0) > limits.maxChars) {
          status = 'capacity'; publish(); throw new Error('reply_context_too_large')
        }
        publish()
        const edge = direction === 'up' ? scroll.scrollTop <= 1 : scroll.scrollHeight - scroll.clientHeight - scroll.scrollTop <= 2
        idle = before === messages.length && edge ? idle + 1 : 0
        if (idle >= 4) {
          if (direction === 'down') context.context_scope.latest_visible = true
          break
        }
        if (step === 239) { status = 'step_limit'; publish(); return context }
      }
    }
    // No new DOM nodes is not proof that the phone's full history is available.
    status = 'web_boundary_unverified'; publish()
    return context
  } finally {
    if (sameChat() && safeToRestore) {
      if (anchor?.isConnected) scroll.scrollTop += anchor.getBoundingClientRect().top - scroll.getBoundingClientRect().top - anchorOffset
      else scroll.scrollTop = wasBottom ? scroll.scrollHeight : originalTop + scroll.scrollHeight - originalHeight
      await wait()
      if (current() && sameChat()) {
        const restored = read()
        if (restored.messages.some(m => !messages.some(saved => key(saved) === key(m)))) throw new Error('reply_stale')
      }
    }
  }
}
