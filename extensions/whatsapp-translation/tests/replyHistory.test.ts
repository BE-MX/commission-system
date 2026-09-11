// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { expect, it, vi } from 'vitest'
import { collectHistory } from '@/whatsapp/replyHistory'
import { adapterFor } from '@/whatsapp/adapter'

function fixture() {
  document.body.innerHTML = readFileSync('tests/fixtures/direct.html', 'utf8')
  const scroll = document.querySelector('[data-testid="conversation-panel-messages"]') as HTMLElement
  scroll.style.overflowY = 'auto'
  let top = 4400
  Object.defineProperties(scroll, {
    clientHeight: { get: () => 400 }, scrollHeight: { get: () => 4800 },
    scrollTop: { get: () => top, set: v => { top = Math.max(0, Math.min(4400, v)) } },
  })
  const render = () => {
    const first = Math.max(0, Math.floor(top / 40) - 5)
    scroll.replaceChildren()
    for (let i = first; i < Math.min(120, first + 20); i++) {
      const row = document.createElement('div'); row.style.alignItems = i % 2 ? 'flex-end' : 'flex-start'
      row.setAttribute('data-id', `false_synthetic-chat_${i}`)
      const bubble = document.createElement('div'); bubble.dataset.testid = 'msg-container'
      const meta = document.createElement('div'); meta.className = 'copyable-text'; meta.dataset.prePlainText = '[10:00, 2026-09-11] Synthetic:'
      const text = document.createElement('span'); text.dataset.testid = 'selectable-text'; text.textContent = i === 50 || i === 51 ? 'OK' : `Synthetic message ${i}`
      meta.append(text); bubble.append(meta); row.append(bubble); scroll.append(row)
    }
  }
  render()
  return { scroll, render }
}
const limits = { maxMessages: 2000, maxChars: 120000 }

it('adapter prevents overlapping collectors even from different assistant instances', async () => {
  fixture(); vi.useFakeTimers()
  try {
    const adapter = adapterFor(document); let active = true
    const first = adapter.collectReplyHistory(limits, () => active, () => {})
    const stopped = expect(first).rejects.toThrow('reply_history_changed')
    await expect(adapter.collectReplyHistory(limits, () => true, () => {})).rejects.toThrow('reply_history_busy')
    expect(adapter.isCollectingHistory()).toBe(true)
    active = false; await vi.runAllTimersAsync(); await stopped
    expect(adapter.isCollectingHistory()).toBe(false)
  } finally { vi.useRealTimers() }
})

it('accumulates 120 virtualized messages and preserves repeated text and full timestamps', async () => {
  const f = fixture()
  const result = await collectHistory(document, limits, () => true, () => {}, async () => f.render())
  expect(result.messages).toHaveLength(120)
  expect(result.messages[0].text).toBe('Synthetic message 0')
  expect(result.messages.at(-1)?.text).toBe('Synthetic message 119')
  expect(result.messages.filter(m => m.text === 'OK')).toHaveLength(2)
  expect(result.messages[0].timestamp).toBe('10:00, 2026-09-11')
  expect(result.context_scope.history_status).toBe('web_boundary_unverified')
  expect(f.scroll.scrollTop).toBe(4400)
  expect(JSON.stringify(result)).not.toContain('synthetic-chat')
})

it('cancellation restores the original chat and never returns a generation snapshot', async () => {
  const f = fixture(); let current = true; let ticks = 0
  await expect(collectHistory(document, limits, () => current, () => {}, async () => {
    f.render(); if (++ticks === 7) current = false
  })).rejects.toThrow('reply_history_changed')
  expect(f.scroll.scrollTop).toBe(4400)
})

it('same-title replacement with different message identities is rejected', async () => {
  const f = fixture(); let ticks = 0
  await expect(collectHistory(document, limits, () => true, () => {}, async () => {
    f.render()
    if (++ticks === 2) for (const row of document.querySelectorAll('[data-id]')) row.setAttribute('data-id', `different_${row.getAttribute('data-id')}`)
  })).rejects.toThrow('reply_history_changed')
})

it('capacity stop retains collected JSON for inspection and does not pretend completeness', async () => {
  const f = fixture(); let count = 0; let status = ''
  await expect(collectHistory(document, { ...limits, maxMessages: 40 }, () => true, result => {
    count = result.messages.length; status = result.context_scope.history_status ?? ''
  }, async () => f.render())).rejects.toThrow('reply_context_too_large')
  expect(count).toBeGreaterThan(40)
  expect(status).toBe('capacity')
})

it('new message arriving during restore invalidates the captured snapshot', async () => {
  const f = fixture(); let boundary = false
  await expect(collectHistory(document, limits, () => true, result => {
    boundary = result.context_scope.history_status === 'web_boundary_unverified'
  }, async () => {
    f.render()
    if (boundary) document.querySelector('[data-testid="selectable-text"]')!.textContent = 'New customer correction'
  })).rejects.toThrow('reply_stale')
})
