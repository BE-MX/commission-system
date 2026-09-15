import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')
const flow = read('../src/views/expo/composables/useTryOnFlow.js')
const shell = read('../src/views/expo/ExpoKiosk.vue')
const capture = read('../src/views/expo/kiosk/CaptureScreen.vue')
const matching = read('../src/views/expo/kiosk/MatchingScreen.vue')
const result = read('../src/views/expo/kiosk/ResultScreen.vue')

test('session upload passes the selected photo processing mode once in the documented position', () => {
  const call = flow.match(/res = await createSession\(([\s\S]*?)\n\s*\)/)?.[1] || ''
  assert.equal((call.match(/customerId\.value/g) || []).length, 1)
  assert.equal((call.match(/photoProcessingMode\.value/g) || []).length, 1)
  assert.match(call, /pendingName\.value \|\| null,\s*photoProcessingMode\.value, sessionRequest\.id/)
})

test('customer journey exposes real stages and keeps the chosen photo treatment visible', () => {
  assert.match(shell, /\u7167\u7247/)
  assert.match(shell, /\u9009\u53d1\u578b/)
  assert.match(shell, /\u751f\u6210/)
  assert.match(shell, /\u5bf9\u6bd4/)
  assert.match(matching, /\u540e\u7eed\u6362\u53d1\u578b\u4e0d\u91cd\u590d\u7f8e\u989c/)
  assert.match(result, /\u9762\u90e8\u4e0e\u76ae\u80a4\u6309\u539f\u7167\u4fdd\u7559/)
})

test('capture has a local quality preflight and customer can explicitly continue', () => {
  assert.match(capture, /qualityChecking/)
  assert.match(capture, /\u4ecd\u7528\u8fd9\u5f20/)
})
