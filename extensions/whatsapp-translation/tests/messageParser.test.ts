import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { describe, expect, it } from 'vitest'

import { adapterFor } from '@/whatsapp/adapter'

function loadDocument(): Document {
  return new JSDOM(readFileSync(new URL('./fixtures/direct-nested-text.html', import.meta.url), 'utf8'), {
    url: 'https://web.whatsapp.com/',
  }).window.document
}

function appendHiddenTimes(document: Document, markup: string): void {
  for (const message of document.querySelectorAll('[data-testid="msg-container"]')) {
    const time = message.querySelector('[data-testid="msg-meta"]')!.textContent!.trim()
    message.querySelector('.copyable-text')!.insertAdjacentHTML('beforeend',
      `<span><span aria-hidden="true">${markup.replace('$TIME', time)}</span></span>`)
  }
}

describe('nested incoming text structures', () => {
  it('parses text through neutral wrappers and known metadata or tail decorations', async () => {
    const messages = await adapterFor(loadDocument()).listUntranslatedIncomingMessages()

    expect(messages.map(message => message.text)).toEqual([
      'Please send the sample details. 🙂',
      'Danke für die Informationen. Wir prüfen die Muster und melden uns morgen.',
    ])
  })

  it.each([
    '<div>Unknown content</div>',
    '<div data-testid="unknown-message-kind"></div>',
    '<img alt="Media attachment">',
    '<div data-testid="image-thumb"><img alt="Media attachment"></div>',
    '<video></video>',
  ])('rejects an unrecognized message child: %s', async (markup) => {
    const document = loadDocument()
    const messages = [...document.querySelectorAll('[data-testid="msg-container"]')]
    for (const message of messages) message.insertAdjacentHTML('afterbegin', markup)

    await expect(adapterFor(document).listUntranslatedIncomingMessages()).resolves.toEqual([])
  })

  it('accepts empty neutral DIV/SPAN layout trees, including labeled placeholders', async () => {
    const document = loadDocument()
    for (const message of document.querySelectorAll('[data-testid="msg-container"]')) {
      message.insertAdjacentHTML('beforeend', '<div class="synthetic-layout"><div><span aria-label="Synthetic placeholder"></span></div><span></span></div>')
    }

    expect(await adapterFor(document).listUntranslatedIncomingMessages()).toHaveLength(2)
  })

  it.each([
    '<div><span>Unknown content</span></div>',
    '<div><span data-testid="unknown-content"></span></div>',
    '<div><img></div>',
    '<div><span role="img"></span></div>',
    '<div style="background-image: url(https://example.invalid/synthetic.png)"></div>',
  ])('rejects semantic or nonempty content inside an apparent empty layout: %s', async (markup) => {
    const document = loadDocument()
    for (const message of document.querySelectorAll('[data-testid="msg-container"]')) {
      message.insertAdjacentHTML('beforeend', markup)
    }

    await expect(adapterFor(document).listUntranslatedIncomingMessages()).resolves.toEqual([])
  })

  it('recognizes matching hidden metadata time without adding it to the translated text', async () => {
    const document = loadDocument()
    appendHiddenTimes(document, '<span>$TIME</span>')

    expect((await adapterFor(document).listUntranslatedIncomingMessages()).map(message => message.text)).toEqual([
      'Please send the sample details. 🙂',
      'Danke für die Informationen. Wir prüfen die Muster und melden uns morgen.',
    ])
  })

  it.each([
    '<span>10:32</span>',
    '<span>Unknown hidden text</span>',
    '<span>$TIME<img></span>',
    '<span>$TIME<span role="img"></span></span>',
    '<span>$TIME<span data-testid="unknown-content"></span></span>',
  ])('rejects unmatched or unsupported hidden metadata: %s', async (markup) => {
    const document = loadDocument()
    appendHiddenTimes(document, markup)

    await expect(adapterFor(document).listUntranslatedIncomingMessages()).resolves.toEqual([])
  })

  it('does not accept the matching hidden time outside the metadata node', async () => {
    const document = loadDocument()
    appendHiddenTimes(document, '<span>$TIME</span>')
    for (const hidden of document.querySelectorAll('[aria-hidden="true"]')) {
      hidden.closest('[data-testid="msg-container"]')!.append(hidden)
    }

    await expect(adapterFor(document).listUntranslatedIncomingMessages()).resolves.toEqual([])
  })

  it('rejects unknown content on an otherwise recognized wrapper path', async () => {
    const document = loadDocument()
    for (const metadata of document.querySelectorAll('.copyable-text')) {
      metadata.parentElement!.prepend(document.createTextNode('Unknown standalone content'))
    }

    await expect(adapterFor(document).listUntranslatedIncomingMessages()).resolves.toEqual([])
  })

  it.each(['img', 'video'])('does not mistake an unmarked %s in text or metadata for an emoji', async (tag) => {
    const document = loadDocument()
    const roots = document.querySelectorAll('span[data-testid="selectable-text"], [data-testid="msg-meta"]')
    for (const root of roots) root.append(document.createElement(tag))

    await expect(adapterFor(document).listUntranslatedIncomingMessages()).resolves.toEqual([])
  })

  it('still excludes outgoing rows, groups and unknown chats with recognized text structure', async () => {
    const outgoing = loadDocument()
    for (const message of outgoing.querySelectorAll('[data-testid="msg-container"]')) {
      message.parentElement!.style.alignItems = 'flex-end'
    }
    await expect(adapterFor(outgoing).listUntranslatedIncomingMessages()).resolves.toEqual([])

    const group = loadDocument()
    group.querySelector('[aria-label="个人主页详情"]')!.setAttribute('aria-label', 'Group details')
    await expect(adapterFor(group).listUntranslatedIncomingMessages()).resolves.toEqual([])

    const unknown = loadDocument()
    unknown.querySelector('[data-testid="conversation-header"]')!.remove()
    await expect(adapterFor(unknown).listUntranslatedIncomingMessages()).resolves.toEqual([])
  })
})
