// @vitest-environment jsdom
import { expect, it, vi } from 'vitest'
import { createReplyView, REPLY_COPY } from '@/content/replyView'
import { REPLY_ERROR_CODES } from '@/shared/replyCodes'

it('localizes every stable reply activation and validation error code', () => {
  for (const code of REPLY_ERROR_CODES) expect(REPLY_COPY[code], code).toMatch(/[\u4e00-\u9fff]/u)
})
it('renders model text literally, localizes risk flags, and makes needs_confirmation unfillable', () => {
  const host = document.createElement('div'); document.body.append(host)
  const shadow = host.attachShadow({ mode: 'closed' })
  const handlers = { generate: vi.fn(), change: vi.fn(), close: vi.fn(), cancel: vi.fn(), fill: vi.fn(), restore: vi.fn() }
  const view = createReplyView(shadow, handlers)
  view.render({ open: true, busy: false, canRestore: false, result: {
    request_id: 'synthetic', conversation_epoch: 'synthetic', context_version: 0, draft_version: 0,
    status: 'needs_confirmation', reply_language: 'en', reply_text: '<img src=x onerror=alert(1)>', meaning_zh: '中文含义',
    rationale_zh: '需要确认', sources: [], claims: [], risk_flags: ['knowledge_unavailable'], missing_information: ['产品尺寸'],
  } })
  expect(shadow.querySelector('img')).toBeNull()
  expect(shadow.textContent).toContain('<img src=x onerror=alert(1)>')
  expect(shadow.textContent).toContain('未取得可用知识依据')
  expect(shadow.textContent).not.toContain('knowledge_unavailable')
  expect([...shadow.querySelectorAll('button')].some(b => b.textContent === '填入输入框')).toBe(false)
  const goal = shadow.querySelector('textarea')!
  goal.value = 'New goal'; goal.dispatchEvent(new Event('input'))
  expect(handlers.change).toHaveBeenCalledTimes(1)
  expect(handlers.generate).not.toHaveBeenCalled()
})
