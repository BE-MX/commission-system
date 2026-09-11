// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { beforeEach, expect, it } from 'vitest'
import { collectReplyContext, maskContacts } from '@/whatsapp/replyContext'
import { ARK_MARKS } from '@/shared/marks'
import { parseIncomingMessages } from '@/whatsapp/messageParser'

beforeEach(() => { document.body.innerHTML = readFileSync('tests/fixtures/direct.html', 'utf8') })
it('collects both directions including already translated originals and retains media placeholders and excludes system text', () => {
  const host = document.createElement('div')
  host.setAttribute(ARK_MARKS.translationHost, '1')
  host.setAttribute(ARK_MARKS.translationState, 'success')
  host.textContent = 'Generated translation must stay private'
  document.querySelector('[data-testid="msg-container"]')!.append(host)
  const result = collectReplyContext(document)
  expect(result.messages.filter(m => m.kind !== "media").map(({ role, text }) => ({ role, text }))).toEqual([
    { role: 'customer', text: 'Can you ship this week?' },
    { role: 'customer', text: 'Thanks 🥰' },
    { role: 'salesperson', text: 'Already sent' },
  ])
  expect(result.context_scope.omitted_media).toBe(true)
  expect(result.context_scope.latest_visible).toBe(false)
})
it.each(['group', 'unknown'])('fails closed for %s', fixture => {
  document.body.innerHTML = readFileSync(`tests/fixtures/${fixture}.html`, 'utf8')
  expect(() => collectReplyContext(document)).toThrow('chat_unsupported')
})

function textRows(values: string[]) {
  const container = document.querySelector('[data-testid="conversation-panel-messages"]')!
  container.replaceChildren()
  for (const [i, text] of values.entries()) {
    const row = document.createElement('div'); row.style.alignItems = i % 2 ? 'flex-end' : 'flex-start'
    const bubble = document.createElement('div'); bubble.setAttribute('data-testid', 'msg-container')
    const metadata = document.createElement('div'); metadata.className = 'copyable-text'; metadata.setAttribute('data-pre-plain-text', 'Synthetic')
    const span = document.createElement('span'); span.setAttribute('data-testid', 'selectable-text'); span.textContent = text
    metadata.append(span); bubble.append(metadata); row.append(bubble); container.append(row)
  }
}
it('collects all loaded messages by default and reports explicit capacity truncation', () => {
  textRows(Array.from({ length: 45 }, (_, i) => `Synthetic message ${i}`))
  expect(collectReplyContext(document).messages[0].text).toBe('Synthetic message 0')
  expect(collectReplyContext(document, 40).messages).toHaveLength(40)
  textRows(['a'.repeat(8000), 'b'.repeat(5000), 'last'])
  const result = collectReplyContext(document, 2000, { maxMessages: 2000, maxChars: 12000 })
  expect(result.messages.map(m => m.text)).toEqual(['b'.repeat(5000), 'last'])
  expect(result.context_scope.truncated).toBe(true)
  textRows(['short', 'x'.repeat(120001)])
  expect(() => collectReplyContext(document)).toThrow('reply_latest_too_long')
})
it('removes quoted duplicates and skips ambiguous direction without guessing', () => {
  const bubble = document.querySelector('[data-testid="msg-container"]')!
  const quote = document.createElement('div'); quote.setAttribute('data-testid', 'quoted-message')
  const span = document.createElement('span'); span.setAttribute('data-testid', 'selectable-text'); span.textContent = 'Quoted duplicate'
  quote.append(span); bubble.prepend(quote)
  expect(collectReplyContext(document).messages[0].text).toBe('Can you ship this week?')
  bubble.parentElement!.style.alignItems = 'center'
  const result = collectReplyContext(document)
  expect(result.skippedUnknown).toBe(true)
  expect(result.messages.some(m => m.text.includes('ship'))).toBe(false)
})
it('masks contacts without changing hair dimensions, units or quantities', () => {
  expect(maskContacts('Email sample@example.test or +1 202-555-0147. 13x4 lace, 18 inches, 150% density, 200 pieces')).toBe('Email [email] or [phone]. 13x4 lace, 18 inches, 150% density, 200 pieces')
})
it('enforces the wire character budget even when masking expands a short email', () => {
  textRows(['a'.repeat(119988), 'x@y.co'])
  expect(collectReplyContext(document).messages.reduce((n, m) => n + m.text.length, 0)).toBeLessThanOrEqual(120000)
  textRows(['a'.repeat(119999), 'x@y.co'])
  expect(collectReplyContext(document).messages.map(({ role, text }) => ({ role, text }))).toEqual([{ role: 'salesperson', text: '[email]' }])
})
it('preserves meaningful line breaks for reply context without changing incoming translation normalization', async () => {
  textRows(['Synthetic placeholder'])
  const text = document.querySelector('[data-testid="selectable-text"]')!
  text.append(document.createElement('br'), document.createTextNode('Size: 13x4'))
  text.append(document.createElement('br'), document.createElement('br'), document.createTextNode('Please confirm.'))
  expect(collectReplyContext(document).messages[0].text).toBe('Synthetic placeholder\nSize: 13x4\n\nPlease confirm.')
  expect((await parseIncomingMessages(document))[0].text).toBe('Synthetic placeholder Size: 13x4 Please confirm.')
})
it('preserves plain paragraph text in reply context', () => {
  textRows([''])
  const text = document.querySelector('[data-testid="selectable-text"]')!
  for (const content of ['First paragraph', 'Second paragraph']) {
    const paragraph = document.createElement('p'); paragraph.textContent = content; text.append(paragraph)
  }
  expect(collectReplyContext(document).messages[0]?.text).toBe('First paragraph\n\nSecond paragraph')
})
it('honors a lowered 6000-character server cap at whole-message boundaries', () => {
  textRows(['a'.repeat(4000), 'b'.repeat(4000)])
  const result = collectReplyContext(document, 20, { maxMessages: 20, maxChars: 6000 })
  expect(result.messages.map(({ role, text }) => ({ role, text }))).toEqual([{ role: 'salesperson', text: 'b'.repeat(4000) }])
  expect(result.context_scope.truncated).toBe(true)
  expect(result.range).toContain('2–2')
  textRows(['x'.repeat(8000)])
  expect(() => collectReplyContext(document, 20, { maxMessages: 20, maxChars: 6000 })).toThrow('reply_latest_too_long')
})
