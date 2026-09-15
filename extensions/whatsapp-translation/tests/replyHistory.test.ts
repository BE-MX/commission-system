// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { expect, it, vi } from 'vitest'
import { collectHistory, createHistoryCollector } from '@/whatsapp/replyHistory'
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

it('waits in place for a temporarily empty virtual window without dropping history', async () => {
  const f = fixture(); let ticks = 0; let waitingTop = -1
  const result = await collectHistory(document, limits, () => true, () => {}, async () => {
    if (ticks === 2) expect(f.scroll.scrollTop).toBe(waitingTop)
    f.render()
    if (++ticks === 2) { waitingTop = f.scroll.scrollTop; f.scroll.replaceChildren() }
  })
  expect(result.messages).toHaveLength(120)
  expect(result.context_scope.latest_visible).toBe(true)
  expect(f.scroll.scrollTop).toBe(4400)
})

it('does not treat a persistently empty window as the history boundary', async () => {
  const f = fixture(); let ticks = 0
  await expect(collectHistory(document, limits, () => true, () => {}, async () => {
    f.render(); if (++ticks >= 2) f.scroll.replaceChildren()
  })).rejects.toThrow('reply_history_changed')
  expect(ticks).toBeLessThan(10)
})

it('still cancels while waiting for an empty history window to recover', async () => {
  const f = fixture(); let ticks = 0; let current = true
  await expect(collectHistory(document, limits, () => current, () => {}, async () => {
    f.render(); if (++ticks === 2) f.scroll.replaceChildren()
    if (ticks === 3) current = false
  })).rejects.toThrow('reply_history_changed')
})

it('rejects different message identities after an empty loading window', async () => {
  const f = fixture(); let ticks = 0
  await expect(collectHistory(document, limits, () => true, () => {}, async () => {
    f.render(); ticks++
    if (ticks === 2) f.scroll.replaceChildren()
    if (ticks >= 3) for (const row of document.querySelectorAll('[data-id]')) row.setAttribute('data-id', `different_${row.getAttribute('data-id')}`)
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
it('rejects a message with an unknown sender arriving during restore', async () => {
  const f = fixture(); let boundary = false
  await expect(collectHistory(document, limits, () => true, result => {
    boundary = result.context_scope.history_status === 'web_boundary_unverified'
  }, async () => {
    f.render()
    if (boundary) { const row = document.createElement('div'); row.innerHTML = '<div data-testid="msg-container">Synthetic unknown direction</div>'; f.scroll.append(row) }
  })).rejects.toThrow('reply_stale')
})

it('reuses history without scrolling and appends new messages while preserving earlier rows', async () => {
  const f = fixture(); const wait = vi.fn(async () => f.render())
  const collector = createHistoryCollector(document, wait)
  const first = await collector.collect(limits, () => true, () => {})
  expect(first.messages).toHaveLength(120)
  wait.mockClear()
  expect((await collector.collect(limits, () => true, () => {})).messages).toEqual(first.messages)
  expect(wait).not.toHaveBeenCalled()
  const row = f.scroll.lastElementChild!.cloneNode(true) as HTMLElement
  row.setAttribute('data-id', 'false_synthetic-chat_120')
  row.querySelector('[data-testid="selectable-text"]')!.textContent = 'New customer message'
  f.scroll.append(row)
  const next = await collector.collect(limits, () => true, () => {})
  expect(next.messages).toHaveLength(121)
  expect(next.messages[0].text).toBe('Synthetic message 0')
  expect(next.messages.at(-1)?.text).toBe('New customer message')
  expect(wait).not.toHaveBeenCalled()
  await expect(collector.collect({ ...limits, maxMessages: 100 }, () => true, () => {})).rejects.toThrow('reply_context_too_large')
})
it('clearing the active chat forces a new capture', async () => {
  const f = fixture(); const wait = vi.fn(async () => f.render())
  const collector = createHistoryCollector(document, wait)
  await collector.collect(limits, () => true, () => {})
  collector.clear(); wait.mockClear()
  await collector.collect(limits, () => true, () => {})
  expect(wait).toHaveBeenCalled()
})
it('edited visible messages trigger a fresh capture instead of retaining stale text', async () => {
  const f = fixture(); let edited = false
  const wait = vi.fn(async () => { f.render(); if (edited) for (const node of f.scroll.querySelectorAll('[data-testid="selectable-text"]')) node.textContent += ' corrected' })
  const collector = createHistoryCollector(document, wait)
  await collector.collect(limits, () => true, () => {})
  edited = true; await wait(); wait.mockClear()
  const result = await collector.collect(limits, () => true, () => {})
  expect(wait).toHaveBeenCalled()
  expect(result.messages.every(m => m.text.endsWith(' corrected'))).toBe(true)
})

it.each([true, false])('removes a deleted tail message when starting at bottom=%s', async atBottom => {
  const f = fixture(); let deleted = false
  const wait = vi.fn(async () => { f.render(); if (deleted) f.scroll.querySelector('[data-id="false_synthetic-chat_119"]')?.remove() })
  const collector = createHistoryCollector(document, wait)
  await collector.collect(limits, () => true, () => {})
  deleted = true; if (!atBottom) f.scroll.scrollTop = 2000
  await wait(); wait.mockClear()
  const result = await collector.collect(limits, () => true, () => {})
  expect(wait).toHaveBeenCalled()
  expect(result.messages).toHaveLength(119)
  expect(result.messages.at(-1)?.text).toBe('Synthetic message 118')
})

import { createAutoReply } from '@/content/autoReply'

it('auto takeover can finish real history collection without treating scroll windows as new messages', async () => {
  const f = fixture(); vi.useFakeTimers()
  try {
    const adapter = adapterFor(document)
    adapter.composerElement()!.textContent = ''
    const collector = createHistoryCollector(document, async () => { await new Promise(resolve => setTimeout(resolve, 10)); f.render() })
    const suggest = vi.fn(async (p) => ({ ...p, status: 'ready', auto_action: 'wait', reply_segments: [], reply_text: 'Wait', reply_language: 'en', meaning_zh: '等待', rationale_zh: '等待', sources: [], claims: [], risk_flags: [], missing_information: [] }))
    // Last row of the synthetic conversation is a customer message for this case.
    const render = f.render
    f.render = () => { render(); const last = f.scroll.querySelector('[data-id="false_synthetic-chat_119"]') as HTMLElement | null; if (last) last.style.alignItems = 'flex-start' }
    f.render()
    const auto = createAutoReply({ snapshot: () => adapter.autoSnapshot(), collect: (_caps, current) => collector.collect(limits, current, () => {}), send: vi.fn() }, {
      capabilities: async () => ({ available: true, history_enabled: true, auto_reply_enabled: true, max_messages: 2000, default_messages: 2000, max_context_chars: 120000, max_draft_chars: 2000, max_goal_chars: 500, timeout_seconds: 120 }), suggest,
    }, () => ({ language: 'auto', fallback: 'en', goal: '' }), vi.fn())
    auto.start(); await vi.advanceTimersByTimeAsync(7000)
    expect(suggest).toHaveBeenCalledTimes(1)
    expect(suggest.mock.calls[0][0].messages).toHaveLength(120)
    auto.stop()
  } finally { vi.useRealTimers() }
})
