import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  focusDialog,
  reconcileSubmittedDraft,
  restoreDialogFocus,
  shouldAutoScroll,
  trapDialogFocus,
} from '../src/views/design/image-studio/state.js'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function openingTags(source, tagName) {
  const tags = []
  let cursor = 0
  while ((cursor = source.indexOf(`<${tagName}`, cursor)) !== -1) {
    let quote = null
    for (let index = cursor; index < source.length; index += 1) {
      const character = source[index]
      if (quote) {
        if (character === quote) quote = null
      } else if (character === '"' || character === "'") quote = character
      else if (character === '>') {
        tags.push(source.slice(cursor, index + 1))
        cursor = index + 1
        break
      }
    }
  }
  return tags
}

function focusable(name) {
  return { name, focusCalls: 0, focus() { this.focusCalls += 1 } }
}

function functionBlock(source, name, nextName) {
  const start = source.indexOf(`function ${name}`)
  const end = source.indexOf(`function ${nextName}`, start + 1)
  return start === -1 ? '' : source.slice(start, end === -1 ? source.length : end)
}

test('submit success clears only the unchanged prompt and sent draft inputs', () => {
  const sentA = { uploadId: 'a', asset: { id: 11 } }
  const sentB = { uploadId: 'b', asset: { id: 12 } }
  const next = { uploadId: 'next', asset: { id: 13 } }
  const currentBase = { id: 22 }

  assert.deepEqual(reconcileSubmittedDraft({
    prompt: 'next turn', attachments: [sentA, sentB, next], baseAsset: currentBase,
  }, {
    sentPrompt: 'sent turn', sentUploadIds: ['a', 'b'], sentBaseId: 21,
  }), {
    prompt: 'next turn', attachments: [next], baseAsset: currentBase,
  })

  assert.deepEqual(reconcileSubmittedDraft({
    prompt: 'sent turn', attachments: [sentA, sentB], baseAsset: { id: 21 },
  }, {
    sentPrompt: 'sent turn', sentUploadIds: ['a', 'b'], sentBaseId: 21,
  }), {
    prompt: '', attachments: [], baseAsset: null,
  })
})

test('dialog focus enters, wraps both directions, restores, and handles no controls', () => {
  const first = focusable('first')
  const last = focusable('last')
  const container = {
    focusCalls: 0,
    focus() { this.focusCalls += 1 },
    querySelectorAll() { return [first, last] },
  }
  assert.equal(focusDialog(container), first)
  assert.equal(first.focusCalls, 1)

  let prevented = 0
  const event = { key: 'Tab', shiftKey: false, preventDefault() { prevented += 1 } }
  assert.equal(trapDialogFocus(event, container, last), true)
  assert.equal(first.focusCalls, 2)
  assert.equal(trapDialogFocus({ ...event, shiftKey: true }, container, first), true)
  assert.equal(last.focusCalls, 1)
  assert.equal(prevented, 2)
  assert.equal(trapDialogFocus({ ...event, shiftKey: true }, container, container), true)
  assert.equal(last.focusCalls, 2)
  assert.equal(trapDialogFocus(event, container, container), true)
  assert.equal(first.focusCalls, 3)

  const empty = { focusCalls: 0, focus() { this.focusCalls += 1 }, querySelectorAll() { return [] } }
  assert.equal(trapDialogFocus(event, empty, null), true)
  assert.equal(empty.focusCalls, 1)
  restoreDialogFocus(last)
  assert.equal(last.focusCalls, 3)
})

test('auto-scroll follows nearby readers, new user messages, and initial loads only', () => {
  const prior = [{ id: 1, role: 'user' }, { id: 2, role: 'assistant' }]
  assert.equal(shouldAutoScroll({ distanceFromBottom: 40, previousMessages: prior, nextMessages: prior }), true)
  assert.equal(shouldAutoScroll({ distanceFromBottom: 400, previousMessages: prior, nextMessages: prior }), false)
  assert.equal(shouldAutoScroll({
    distanceFromBottom: 400,
    previousMessages: prior,
    nextMessages: [...prior, { id: 3, role: 'user' }],
  }), true)
  assert.equal(shouldAutoScroll({
    distanceFromBottom: 400,
    previousMessages: prior,
    nextMessages: [...prior, { id: 4, role: 'assistant' }],
  }), false)
  assert.equal(shouldAutoScroll({ distanceFromBottom: 400, previousMessages: [], nextMessages: prior }), true)
})

test('composer and studio disable destructive draft actions while sending', () => {
  const composer = read('../src/views/design/image-studio/components/PromptComposer.vue')
  const page = read('../src/views/design/image-studio/ImageStudio.vue')
  const studio = read('../src/views/design/image-studio/composables/useImageStudio.js')
  const buttons = openingTags(composer, 'button')
  const clearBase = buttons.find(tag => tag.includes("emit('clear-base')")) || ''
  const remove = buttons.find(tag => tag.includes("emit('remove'")) || ''
  const promptComposer = openingTags(page, 'PromptComposer')[0] || ''

  assert.match(clearBase, /:disabled="sending"/)
  assert.match(remove, /:disabled="sending \|\| item\.status === 'uploading'"/)
  assert.match(promptComposer, /@clear-base="studio\.clearBaseAsset"/)
  assert.doesNotMatch(promptComposer, /baseAsset\.value\s*=\s*null/)
  for (const block of [
    functionBlock(studio, 'removeAttachment', 'submit'),
    functionBlock(studio, 'chooseBaseAsset', 'clearBaseAsset'),
    functionBlock(studio, 'clearBaseAsset', 'openLightbox'),
  ]) assert.match(block, /if \(sendInFlight\.value\) return/)
})

test('studio uses submit snapshots, independent terminal refresh, focus traps, and guarded scroll', () => {
  const studio = read('../src/views/design/image-studio/composables/useImageStudio.js')
  const sidebar = read('../src/views/design/image-studio/components/ConversationSidebar.vue')
  const lightbox = read('../src/views/design/image-studio/components/ImageLightbox.vue')
  const thread = read('../src/views/design/image-studio/components/MessageThread.vue')
  const polling = studio.match(/function startActivePolling[\s\S]*?(?=\r?\n  async function loadConfig)/)?.[0] || ''
  const drawer = openingTags(sidebar, 'div').find(tag => tag.includes('drawer-panel')) || ''
  const lightboxDialog = openingTags(lightbox, 'div').find(tag => tag.includes('role="dialog"')) || ''

  assert.match(studio, /const sentPrompt = prompt\.value\r?\n/)
  assert.match(studio, /prompt: sentPrompt\.trim\(\)/)
  for (const snapshot of ['sentUploadIds', 'sentBaseId']) assert.match(studio, new RegExp(`const ${snapshot}`))
  assert.match(studio, /reconcileSubmittedDraft\(/)
  assert.ok(polling.indexOf('refreshCurrentSession(merged.session_id)') < polling.indexOf('loadConfig().catch('))
  assert.match(drawer, /ref="drawerPanel"/)
  assert.match(drawer, /tabindex="-1"/)
  assert.match(drawer, /@keydown="onDialogKeydown"/)
  assert.match(lightboxDialog, /ref="lightboxDialog"/)
  assert.match(lightboxDialog, /tabindex="-1"/)
  assert.match(lightboxDialog, /@keydown="onDialogKeydown"/)
  for (const source of [sidebar, lightbox]) {
    assert.match(source, /focusDialog/)
    assert.match(source, /trapDialogFocus/)
    assert.match(source, /restoreDialogFocus/)
  }
  assert.match(lightbox, /if \(value && !previous\)/)
  assert.match(thread, /shouldAutoScroll/)
  assert.match(thread, /if \(autoScroll && pane\.value\)/)
})
