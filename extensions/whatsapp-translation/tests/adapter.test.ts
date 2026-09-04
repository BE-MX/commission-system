import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { describe, expect, it, vi } from 'vitest'

import { adapterFor, runOutgoingTranslation } from '@/whatsapp/adapter'

function loadFixture(name: string): Document {
  return new JSDOM(readFileSync(new URL(`./fixtures/${name}.html`, import.meta.url), 'utf8')).window.document
}

const directFixture = loadFixture('direct')
const directEmptyFixture = loadFixture('direct-empty')
const groupFixture = loadFixture('group')
const unknownFixture = loadFixture('unknown')
const noChatFixture = loadFixture('no-chat')

describe('WhatsApp adapter', () => {
  it('classifies current direct, unsupported and no-chat structures', () => {
    expect(adapterFor(directFixture).inspectChat().kind).toBe('direct')
    expect(adapterFor(directEmptyFixture).inspectChat().kind).toBe('direct')
    expect(adapterFor(groupFixture).inspectChat().kind).toBe('unknown')
    expect(adapterFor(unknownFixture).inspectChat().kind).toBe('unknown')
    expect(adapterFor(noChatFixture).inspectChat().kind).toBe('no_chat')
  })

  it('fails closed for unsupported chats', async () => {
    await expect(adapterFor(groupFixture).listUntranslatedIncomingMessages()).resolves.toEqual([])
    expect(adapterFor(groupFixture).readComposer()).toBe('')
    await adapterFor(groupFixture).replaceComposer('Should not be written')
    expect(groupFixture.querySelector('footer div')?.textContent).toBe('Group draft')
    expect(adapterFor(unknownFixture).readComposer()).toBe('')
  })

  it('parses current WhatsApp incoming text messages and excludes outgoing messages', async () => {
    const messages = await adapterFor(directFixture).listUntranslatedIncomingMessages()

    expect(messages.map(message => message.text)).toEqual(['Can you ship this week?', 'Thanks'])
    expect(messages[0].localKey).toMatch(/^[0-9a-f]{64}$/)
    expect(JSON.stringify(messages)).not.toMatch(/@c\.us|data-id|phone|contact/)
  })

  it('creates distinct local keys for repeated incoming text', async () => {
    const document = loadFixture('direct')
    const root = document.getElementById('main') as HTMLElement
    const source = root.querySelector('[data-testid="msg-container"]')?.parentElement as HTMLElement
    for (let index = 0; index < 2; index += 1) {
      const duplicate = document.createElement('div')
      duplicate.style.alignItems = 'flex-start'
      duplicate.style.display = 'flex'
      duplicate.innerHTML = `
        <div data-testid="msg-container">
          <div class="copyable-text" data-pre-plain-text="[18:45, 2026-09-03] Customer: ">
            <span data-testid="selectable-text">Repeated text</span>
          </div>
        </div>
      `
      source.parentElement?.insertBefore(duplicate, source)
    }

    const messages = await adapterFor(document).listUntranslatedIncomingMessages()

    expect(messages.map(message => message.text).slice(0, 2)).toEqual(['Repeated text', 'Repeated text'])
    expect(messages[0].localKey).not.toBe(messages[1].localKey)
  })

  it('replaces only the confirmed composer and never dispatches send controls', async () => {
    const composer = directFixture.querySelector('footer div') as HTMLElement
    const eventTypes: string[] = []
    const prohibitedTypes: string[] = []
    const record = (event: Event) => {
      if (['beforeinput', 'input'].includes(event.type)) eventTypes.push(event.type)
      if (['click', 'submit'].includes(event.type)) prohibitedTypes.push(event.type)
    }
    composer.addEventListener('beforeinput', record)
    composer.addEventListener('input', record)
    composer.addEventListener('click', record)
    composer.addEventListener('submit', record)

    await adapterFor(directFixture).replaceComposer('Translated preview')

    expect(composer.textContent).toBe('Translated preview')
    expect(eventTypes).toEqual(['beforeinput', 'input'])
    expect(prohibitedTypes).toEqual([])
    expect(adapterFor(directFixture)).not.toHaveProperty('send')
  })

  it('keeps same-name group messages out of the translation boundary', async () => {
    expect(adapterFor(groupFixture).inspectChat().kind).toBe('unknown')
    await expect(adapterFor(groupFixture).listUntranslatedIncomingMessages()).resolves.toEqual([])
    expect(adapterFor(groupFixture).attachOutgoingControl(() => {})).toBeNull()
  })

  it('removes outgoing controls when the active chat becomes unsupported', () => {
    adapterFor(directFixture).attachOutgoingControl(() => {})
    expect(directFixture.querySelector('[data-ark-outgoing-control="1"]')).not.toBeNull()

    adapterFor(groupFixture).attachOutgoingControl(() => {})
    expect(groupFixture.querySelector('[data-ark-outgoing-control="1"]')).toBeNull()
  })

  it('shows progress and a retryable failure on the outgoing translation button', async () => {
    const document = loadFixture('direct')
    let rejectTranslation: ((error: Error) => void) | undefined
    const translation = new Promise<void>((_resolve, reject) => {
      rejectTranslation = reject
    })
    const button = document.createElement('button')
    const task = runOutgoingTranslation(button, vi.fn(() => translation))

    expect(button.disabled).toBe(true)
    expect(button.textContent).toBe('翻译中…')

    rejectTranslation?.(new Error('translation_invalid_response'))
    await task

    expect(button.disabled).toBe(false)
    expect(button.textContent).toBe('翻译失败，重试')
    expect(adapterFor(document).attachOutgoingControl(() => {})?.shadowRoot).toBeNull()
  })
})
