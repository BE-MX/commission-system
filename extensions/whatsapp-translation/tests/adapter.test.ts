import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { describe, expect, it } from 'vitest'

import { adapterFor } from '@/whatsapp/adapter'

function loadFixture(name: string): Document {
  return new JSDOM(readFileSync(new URL(`./fixtures/${name}.html`, import.meta.url), 'utf8')).window.document
}

const directFixture = loadFixture('direct')
const groupFixture = loadFixture('group')
const unknownFixture = loadFixture('unknown')
const noChatFixture = loadFixture('no-chat')

describe('WhatsApp adapter', () => {
  it('classifies direct, group, unknown and no-chat states', () => {
    expect(adapterFor(directFixture).inspectChat().kind).toBe('direct')
    expect(adapterFor(groupFixture).inspectChat().kind).toBe('group')
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

  it('returns only eligible incoming direct messages without identifiers', async () => {
    const messages = await adapterFor(directFixture).listUntranslatedIncomingMessages()

    expect(messages.map(message => message.text)).toEqual(['Can you ship this week?'])
    expect(messages[0].localKey).toMatch(/^[0-9a-f]{64}$/)
    expect(JSON.stringify(messages)).not.toMatch(/@c\.us|data-id|phone|contact/)
  })

  it('creates distinct local keys for repeated incoming text', async () => {
    const document = loadFixture('direct')
    const root = document.getElementById('main') as HTMLElement
    const source = root.querySelector('.message-in') as HTMLElement
    for (let index = 0; index < 2; index += 1) {
      const duplicate = document.createElement('div')
      duplicate.className = 'message-in'
      duplicate.innerHTML = '<div class="copyable-text"><span class="selectable-text">Repeated text</span></div>'
      root.insertBefore(duplicate, source)
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
})
