import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { describe, expect, it, vi } from 'vitest'

import { adapterFor } from '@/whatsapp/adapter'

function loadFixture(name: string): Document {
  return new JSDOM(readFileSync(new URL(`./fixtures/${name}.html`, import.meta.url), 'utf8')).window.document
}

const directFixture = loadFixture('direct')
const directForwardedFixture = loadFixture('direct-forwarded')
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

  it('parses forwarded pure text without widening unsupported chat structures', async () => {
    const messages = await adapterFor(directForwardedFixture).listUntranslatedIncomingMessages()

    expect(messages.map(message => message.text)).toEqual(['Forwarded synthetic text'])
    await expect(adapterFor(groupFixture).listUntranslatedIncomingMessages()).resolves.toEqual([])
    await expect(adapterFor(unknownFixture).listUntranslatedIncomingMessages()).resolves.toEqual([])
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
    const document = loadFixture('direct')
    const composer = document.querySelector('footer div') as HTMLElement
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
    const nativeInsert = vi.fn((command: string, _showUi: boolean, value: string) => {
      if (command !== 'insertText') return false
      composer.replaceChildren(document.createTextNode(value))
      composer.dispatchEvent(new document.defaultView!.InputEvent('input', {
        bubbles: true,
        data: value,
        inputType: 'insertText',
      }))
      return true
    })
    Object.defineProperty(document, 'execCommand', { configurable: true, value: nativeInsert })

    const replaced = await adapterFor(document).replaceComposer('Translated preview')

    expect(replaced).toBe(true)
    expect(composer.textContent).toBe('Translated preview')
    expect(nativeInsert).toHaveBeenCalledWith('insertText', false, 'Translated preview')
    expect(eventTypes).toEqual(['input'])
    expect(prohibitedTypes).toEqual([])
    expect(adapterFor(document)).not.toHaveProperty('send')
  })

  it('reports failure when the controlled composer rejects or rewrites the native edit', async () => {
    const rejectedDocument = loadFixture('direct')
    Object.defineProperty(rejectedDocument, 'execCommand', { configurable: true, value: () => false })
    await expect(adapterFor(rejectedDocument).replaceComposer('Translated preview')).resolves.toBe(false)

    const rewrittenDocument = loadFixture('direct')
    const composer = rewrittenDocument.querySelector('footer div') as HTMLElement
    Object.defineProperty(rewrittenDocument, 'execCommand', {
      configurable: true,
      value: (_command: string, _showUi: boolean, _value: string) => {
        composer.textContent = 'Editor-owned value'
        return true
      },
    })
    await expect(adapterFor(rewrittenDocument).replaceComposer('Translated preview')).resolves.toBe(false)
  })

  it('mounts the toolbar as the first child of the footer in a closed shadow and cleans on unsupported chat', () => {
    const root = adapterFor(directFixture)
    const footer = directFixture.querySelector('footer') as HTMLElement
    const shadow = root.mountComposerToolbar()
    expect(footer.firstElementChild?.getAttribute('data-ark-outgoing-control')).toBe('1')
    expect(shadow).not.toBeNull()
    expect(shadow?.host).toBe(footer.firstElementChild)

    adapterFor(groupFixture).mountComposerToolbar()
    expect(groupFixture.querySelector('[data-ark-outgoing-control="1"]')).toBeNull()
  })

  it('returns the trimmed current chat title only for direct chats', () => {
    expect(adapterFor(directFixture).chatTitle()).toBe('Customer')
    expect(adapterFor(groupFixture).chatTitle()).toBe('')
  })

  it('exposes the dark theme decision from the body class', () => {
    const doc = loadFixture('direct')
    doc.body.classList.add('dark')
    expect(adapterFor(doc).isDarkTheme()).toBe(true)
  })
})
