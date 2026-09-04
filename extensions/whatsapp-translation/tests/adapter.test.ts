import { readFileSync } from 'node:fs'
import { JSDOM } from 'jsdom'
import { describe, expect, it, vi } from 'vitest'

import { adapterFor } from '@/whatsapp/adapter'
import { installControlledComposer } from './support/controlledComposer'

function loadFixture(name: string): Document {
  return new JSDOM(readFileSync(new URL(`./fixtures/${name}.html`, import.meta.url), 'utf8'), {
    url: 'https://web.whatsapp.com/',
  }).window.document
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

    expect(messages.map(message => message.text)).toEqual(['Can you ship this week?', 'Thanks 🥰'])
    expect(messages[0].localKey).toMatch(/^[0-9a-f]{64}$/)
    expect(JSON.stringify(messages)).not.toMatch(/@c\.us|data-id|phone|contact/)
  })

  it('parses forwarded pure text without widening unsupported chat structures', async () => {
    const messages = await adapterFor(directForwardedFixture).listUntranslatedIncomingMessages()

    expect(messages.map(message => message.text)).toEqual(['Forwarded synthetic text'])
    await expect(adapterFor(groupFixture).listUntranslatedIncomingMessages()).resolves.toEqual([])
    await expect(adapterFor(unknownFixture).listUntranslatedIncomingMessages()).resolves.toEqual([])
  })

  it('fails closed when an otherwise valid text bubble contains unknown unmarked content', async () => {
    const document = loadFixture('direct-forwarded')
    const message = document.querySelector('[data-testid="msg-container"]') as HTMLElement
    const unknown = document.createElement('div')
    unknown.className = 'synthetic-unknown-node'
    unknown.textContent = 'Unsupported content'
    message.prepend(unknown)

    await expect(adapterFor(document).listUntranslatedIncomingMessages()).resolves.toEqual([])
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

  it('keeps a queued message key stable after earlier messages enter loading state', async () => {
    const document = loadFixture('direct')
    const messagePanel = document.querySelector('[data-testid="conversation-panel-messages"]') as HTMLElement
    const unsupportedRows = [...messagePanel.children]
    messagePanel.replaceChildren()

    for (let index = 0; index < 4; index += 1) {
      const row = document.createElement('div')
      row.style.alignItems = 'flex-start'
      row.style.display = 'flex'
      row.innerHTML = `
        <div data-testid="msg-container">
          <div class="copyable-text" data-pre-plain-text="[18:4${index}, 2026-09-03] Synthetic: ">
            <span data-testid="selectable-text">Synthetic text ${index + 1}</span>
          </div>
        </div>
      `
      messagePanel.append(row)
    }

    const firstScan = await adapterFor(document).listUntranslatedIncomingMessages()
    for (const message of firstScan.slice(0, 3)) {
      const host = document.createElement('div')
      host.setAttribute('data-ark-translation-host', '1')
      host.setAttribute('data-ark-translation-state', 'loading')
      message.element.append(host)
    }
    const secondScan = await adapterFor(document).listUntranslatedIncomingMessages()

    expect(firstScan).toHaveLength(4)
    expect(secondScan).toHaveLength(1)
    expect(secondScan[0].text).toBe('Synthetic text 4')
    expect(secondScan[0].localKey).toBe(firstScan[3].localKey)

    messagePanel.replaceChildren(...unsupportedRows)
  })

  it('does not reuse a settled message key for a later identical message', async () => {
    const document = loadFixture('direct')
    const messagePanel = document.querySelector('[data-testid="conversation-panel-messages"]') as HTMLElement
    messagePanel.replaceChildren()
    for (let index = 0; index < 2; index += 1) {
      const row = document.createElement('div')
      row.style.alignItems = 'flex-start'
      row.innerHTML = `
        <div data-testid="msg-container">
          <div class="copyable-text" data-pre-plain-text="[18:4${index}, 2026-09-03] Synthetic: ">
            <span data-testid="selectable-text">OK again</span>
          </div>
        </div>
      `
      messagePanel.append(row)
    }

    const firstScan = await adapterFor(document).listUntranslatedIncomingMessages()
    const host = document.createElement('div')
    host.setAttribute('data-ark-translation-host', '1')
    host.setAttribute('data-ark-translation-state', 'success')
    firstScan[0].element.append(host)
    const secondScan = await adapterFor(document).listUntranslatedIncomingMessages()

    expect(secondScan).toHaveLength(1)
    expect(secondScan[0].localKey).toBe(firstScan[1].localKey)
    expect(secondScan[0].localKey).not.toBe(firstScan[0].localKey)
  })

  it('replaces only the confirmed composer and never dispatches send controls', async () => {
    const document = loadFixture('direct')
    const composer = document.querySelector('footer div') as HTMLElement
    const footer = document.querySelector('footer') as HTMLElement
    const send = document.createElement('button')
    send.type = 'button'
    send.dataset.testid = 'compose-btn-send'
    send.click = vi.fn()
    footer.append(send)
    const form = document.createElement('form')
    form.submit = vi.fn()
    form.requestSubmit = vi.fn()
    document.body.append(form)
    const editor = installControlledComposer(document, composer)
    const eventTypes: string[] = []
    const prohibitedTypes: string[] = []
    const record = (event: Event) => {
      if (['beforeinput', 'input'].includes(event.type)) eventTypes.push(event.type)
      if (['click', 'submit'].includes(event.type)) prohibitedTypes.push(event.type)
    }
    composer.addEventListener('beforeinput', record)
    composer.addEventListener('input', record)
    document.addEventListener('click', record, true)
    document.addEventListener('submit', record, true)
    const replaced = await adapterFor(document).replaceComposer('Translated preview')

    expect(replaced).toBe(true)
    expect(composer.textContent).toBe('Translated preview')
    expect(editor.commandCount()).toBe(1)
    expect(eventTypes).toEqual(['beforeinput'])
    expect(prohibitedTypes).toEqual([])
    expect(send.click).not.toHaveBeenCalled()
    expect(form.submit).not.toHaveBeenCalled()
    expect(form.requestSubmit).not.toHaveBeenCalled()
    expect(adapterFor(document)).not.toHaveProperty('send')
  })

  it('reports failure when the controlled composer rejects or rewrites the native edit', async () => {
    const rejectedDocument = loadFixture('direct')
    const rejectedComposer = rejectedDocument.querySelector('footer div') as HTMLElement
    const rejectedEditor = installControlledComposer(rejectedDocument, rejectedComposer, { mode: 'reject' })
    await expect(adapterFor(rejectedDocument).replaceComposer('Translated preview')).resolves.toBe(false)
    expect(rejectedEditor.commandCount()).toBe(1)
    expect(rejectedComposer.textContent).toBe('Current draft')

    const rewrittenDocument = loadFixture('direct')
    const composer = rewrittenDocument.querySelector('footer div') as HTMLElement
    installControlledComposer(rewrittenDocument, composer, { mode: 'rewrite' })
    await expect(adapterFor(rewrittenDocument).replaceComposer('Translated preview')).resolves.toBe(false)
  })

  it('replaces text through the beforeinput command accepted by a Lexical-controlled composer', async () => {
    const document = loadFixture('direct')
    const composer = document.querySelector('footer div') as HTMLElement
    const editor = installControlledComposer(document, composer)
    composer.setAttribute('data-lexical-editor', 'true')

    await expect(adapterFor(document).replaceComposer('Translated preview')).resolves.toBe(true)
    expect(composer.textContent).toBe('Translated preview')
    expect(editor.commandCount()).toBe(1)
  })

  it('does not overwrite a draft that changes while the editor selection is synchronizing', async () => {
    const document = loadFixture('direct')
    const composer = document.querySelector('footer div') as HTMLElement
    const editor = installControlledComposer(document, composer, { manualFrames: true })

    const replacement = adapterFor(document).replaceComposer('Translated preview')
    composer.textContent = 'User edit during selection sync'
    editor.flushFrame()
    await Promise.resolve()
    editor.flushFrame()

    await expect(replacement).resolves.toBe(false)
    expect(composer.textContent).toBe('User edit during selection sync')
    expect(editor.commandCount()).toBe(0)
  })

  it('waits for a refocused editor to restore its old caret before selecting the draft', async () => {
    const document = loadFixture('direct')
    const composer = document.querySelector('footer div') as HTMLElement
    const editor = installControlledComposer(document, composer)
    // The public focus event schedules the editor-owned caret restoration seen
    // on WhatsApp. It must finish before the adapter establishes its selection.
    composer.addEventListener('focus', () => {
      void Promise.resolve().then(() => {
        document.defaultView!.getSelection()!.collapse(composer.firstChild, 0)
      })
    }, { once: true })

    await expect(adapterFor(document).replaceComposer('Translated preview')).resolves.toBe(true)
    expect(composer.textContent).toBe('Translated preview')
    expect(editor.commandCount()).toBe(1)
  })

  it('does not dispatch an edit if the selected draft collapses before beforeinput', async () => {
    const document = loadFixture('direct')
    const composer = document.querySelector('footer div') as HTMLElement
    const editor = installControlledComposer(document, composer, { manualFrames: true })
    composer.focus()

    const replacement = adapterFor(document).replaceComposer('Translated preview')
    document.defaultView!.getSelection()!.collapse(composer.firstChild, 0)
    editor.flushFrame()

    await expect(replacement).resolves.toBe(false)
    expect(editor.commandCount()).toBe(0)
    expect(composer.textContent).toBe('Current draft')
  })

  it('does not write after the owning chat generation becomes stale', async () => {
    const document = loadFixture('direct')
    const composer = document.querySelector('footer div') as HTMLElement
    const editor = installControlledComposer(document, composer, { manualFrames: true })
    let currentGeneration = true

    const replacement = adapterFor(document).replaceComposer('Translated preview', () => currentGeneration)
    currentGeneration = false
    editor.flushFrame()
    await Promise.resolve()
    editor.flushFrame()

    await expect(replacement).resolves.toBe(false)
    expect(composer.textContent).toBe('Current draft')
    expect(editor.commandCount()).toBe(0)
  })

  it('collapses a rejected full selection so the next keystroke cannot erase the draft', async () => {
    const document = loadFixture('direct')
    const composer = document.querySelector('footer div') as HTMLElement
    installControlledComposer(document, composer, { mode: 'reject' })

    await expect(adapterFor(document).replaceComposer('Translated preview')).resolves.toBe(false)

    const selection = document.defaultView!.getSelection()!
    expect(selection.rangeCount).toBe(1)
    expect(selection.isCollapsed).toBe(true)
    expect(selection.anchorNode === composer || composer.contains(selection.anchorNode)).toBe(true)
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
