// @vitest-environment jsdom
import { readFileSync } from 'node:fs'
import { afterEach, expect, it, vi } from 'vitest'
import { adapterFor } from '@/whatsapp/adapter'
afterEach(() => vi.useRealTimers())
function setup() {
  document.body.innerHTML = readFileSync('tests/fixtures/direct.html', 'utf8')
  const adapter = adapterFor(document); let draft = ''
  vi.spyOn(adapter, 'readComposer').mockImplementation(() => draft)
  vi.spyOn(adapter, 'replaceComposer').mockImplementation(async text => { draft = text; return true })
  const button = document.createElement('button'); button.dataset.testid = 'compose-btn-send'
  button.getClientRects = () => [{ width: 20, height: 20 }] as unknown as DOMRectList
  document.querySelector('footer')!.append(button)
  const append = (text: string) => {
    const row = document.querySelector('[data-testid="msg-container"]')!.parentElement!.cloneNode(true) as HTMLElement
    row.style.alignItems = 'flex-end'; row.setAttribute('data-id', 'true_synthetic_new')
    row.querySelector('[data-testid="selectable-text"]')!.textContent = text
    Array.from(document.querySelectorAll('[data-testid="msg-container"]')).at(-1)!.parentElement!.after(row)
  }
  return { adapter, button, append, write: (text: string) => { draft = text }, clear: () => { draft = '' } }
}
it('clicks once and requires a new outgoing bubble plus empty composer', async () => {
  const s = setup(); vi.useFakeTimers(); const clicked = vi.fn(() => { s.append('Hello'); s.clear() }); s.button.onclick = clicked
  const pending = s.adapter.sendAutomatic('Hello', () => true)
  await vi.runAllTimersAsync(); expect(await pending).toBe(true); expect(clicked).toHaveBeenCalledTimes(1)
})
it('does not click after another device sends during composer replacement', async () => {
  const s = setup(); const clicked = vi.fn(); s.button.onclick = clicked
  vi.spyOn(s.adapter, 'replaceComposer').mockImplementation(async text => { s.write(text); s.append('Other device reply'); return true })
  expect(await s.adapter.sendAutomatic('Hello', () => true)).toBe(false); expect(clicked).not.toHaveBeenCalled()
})
it('uncertain send clicks once and returns failure without retry', async () => {
  const s = setup(); vi.useFakeTimers(); const clicked = vi.fn(); s.button.onclick = clicked
  const pending = s.adapter.sendAutomatic('Hello', () => true)
  await vi.runAllTimersAsync(); expect(await pending).toBe(false); expect(clicked).toHaveBeenCalledTimes(1)
})
it.each(['group', 'unknown'])('does not send in %s chats', async kind => {
  const s = setup(); if (kind === 'group') document.querySelector('[aria-label="个人主页详情"]')?.setAttribute('aria-label', '群组信息')
  else document.querySelector('[data-testid="conversation-header"]')?.remove()
  const clicked = vi.fn(); s.button.onclick = clicked
  expect(await s.adapter.sendAutomatic('Hello', () => true)).toBe(false); expect(clicked).not.toHaveBeenCalled()
})
