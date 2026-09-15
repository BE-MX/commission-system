import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'

const flow = await readFile(new URL('../src/views/expo/composables/useTryOnFlow.js', import.meta.url), 'utf8')
const matching = await readFile(new URL('../src/views/expo/kiosk/MatchingScreen.vue', import.meta.url), 'utf8')
const scene = await readFile(new URL('../src/views/expo/kiosk/SceneScreen.vue', import.meta.url), 'utf8')
const api = await readFile(new URL('../src/api/expo.js', import.meta.url), 'utf8')

test('customer flow has no prompt-version picker or payload', () => {
  for (const source of [flow, matching, scene]) {
    assert.doesNotMatch(source, /PromptVersionPicker|promptVersionReady|promptVersionId/)
  }
  assert.doesNotMatch(api, /prompt_version_id|prompt-versions\/picker/)
})

test('upload flow owns the only photo-processing choice', () => {
  assert.match(flow, /photoProcessingMode/)
  assert.match(api, /photo_processing_mode/)
  assert.match(flow, /randomUUID/)
  assert.match(api, /client_request_id/)
})
