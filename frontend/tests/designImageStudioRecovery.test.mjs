import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

function read(relativePath) {
  return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
}

function getOpeningTag(source, componentName) {
  const start = source.indexOf(`<${componentName}`)
  if (start === -1) return ''
  let quote = null
  for (let index = start; index < source.length; index += 1) {
    const character = source[index]
    if (quote) {
      if (character === quote) quote = null
    } else if (character === '"' || character === "'") {
      quote = character
    } else if (character === '>') {
      return source.slice(start, index + 1)
    }
  }
  return ''
}

test('studio restores drafts and protects initialization from user navigation races', () => {
  const source = read('../src/views/design/image-studio/composables/useImageStudio.js')
  assert.match(
    source,
    /asset_type\s*===\s*['"]upload['"][\s\S]*status\s*===\s*['"]draft['"]|status\s*===\s*['"]draft['"][\s\S]*asset_type\s*===\s*['"]upload['"]/,
  )
  assert.match(source, /uploadId:\s*`draft-\$\{asset\.id\}`/)
  assert.match(source, /acceptConversationResponse\(initializeGeneration,\s*conversationGeneration\)/)
  assert.match(source, /loadSessions\([^)]*initializeGeneration/)
  assert.match(source, /async function newConversation\(\)[\s\S]*?conversationGeneration \+= 1/)
  assert.match(source, /mergeSession\(session\)/)
  assert.doesNotMatch(source, /sessions\.value\s*=\s*append\s*\?\s*\[\.\.\.sessions\.value/)
})

test('active polling starts before non-blocking thumbnail hydration', () => {
  const source = read('../src/views/design/image-studio/composables/useImageStudio.js')
  const pollingIndex = source.indexOf('startActivePolling(tracked)')
  const hydrationIndex = source.indexOf('void hydrateThumbnails(')
  assert.ok(pollingIndex > -1)
  assert.ok(hydrationIndex > pollingIndex)
  assert.match(source, /void hydrateThumbnails\([\s\S]*?\)\.catch\(/)
})

test('upload limit, disclosure, lightbox failures, and moderation retry are explicit', () => {
  const composer = read('../src/views/design/image-studio/components/PromptComposer.vue')
  const page = read('../src/views/design/image-studio/ImageStudio.vue')
  const studio = read('../src/views/design/image-studio/composables/useImageStudio.js')
  const thread = read('../src/views/design/image-studio/components/MessageThread.vue')
  const card = read('../src/views/design/image-studio/components/GenerationCard.vue')
  assert.match(composer, /maxUploadBytes/)
  assert.match(composer, /:max-size-mb="maxUploadMb"/)
  assert.doesNotMatch(composer, /:max-size-mb="20"/)
  const promptComposerTag = getOpeningTag(page, 'PromptComposer')
  const messageThreadTag = getOpeningTag(page, 'MessageThread')
  assert.match(promptComposerTag, /:max-upload-bytes="studio\.config\.value\.max_upload_bytes"/)
  assert.doesNotMatch(messageThreadTag, /max-upload-bytes/)
  assert.match(studio, /async function openLightbox[\s\S]*try\s*\{[\s\S]*catch/)
  assert.match(studio, /无法读取原图，请稍后重试/)
  assert.match(thread, /第三方 AI 服务处理/)
  assert.match(thread, /请勿上传敏感资料/)
  assert.match(card, /canRetry/)
  assert.match(card, /v-if="canRetry"/)
})

test('new conversation preserves the current workspace until creation succeeds', () => {
  const studio = read('../src/views/design/image-studio/composables/useImageStudio.js')
  const page = read('../src/views/design/image-studio/ImageStudio.vue')
  const newConversation = studio.match(/async function newConversation\(\)[\s\S]*?(?=\n  async function ensureSession)/)?.[0] || ''
  assert.match(newConversation, /if \(newSessionInFlight\.value\)/)
  assert.match(newConversation, /conversationGeneration \+= 1/)
  assert.match(newConversation, /drawerOpen\.value = false/)
  assert.match(newConversation, /newSessionInFlight\.value = true/)
  assert.match(newConversation, /finally[\s\S]*newSessionInFlight\.value = false/)
  assert.doesNotMatch(newConversation, /polling\.stopPolling|assetUrls\.beginBatch/)
  assert.doesNotMatch(newConversation, /currentSessionId\.value = null|messages\.value = \[\]|assets\.value = \[\]|jobs\.value = \[\]|draftAttachments\.value = \[\]|baseAsset\.value = null/)
  assert.match(studio, /const canSend = computed\([\s\S]*!newSessionInFlight\.value/)
  assert.match(studio, /async function uploadReference[\s\S]*newSessionInFlight\.value/)
  assert.match(studio, /async function ensureSession\(\)[\s\S]*return sessionCreationPromise \|\| newConversation\(\)/)
  assert.match(studio, /newSessionInFlight,[\s\S]*newConversation/)
  assert.match(page, /:upload-disabled="[^"]*studio\.newSessionInFlight\.value/)
})
