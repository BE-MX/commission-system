import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  recoverComposerDrafts,
  reconcileTurnResult,
  safeBusinessErrorMessage,
} from '../src/views/design/image-studio/state.js'

async function importStudioPureHelpers() {
  const source = readFileSync(new URL(
    '../src/views/design/image-studio/composables/useImageStudio.js', import.meta.url,
  ), 'utf8')
  const withoutImports = source.replace(/^import[\s\S]*?from\s+['"][^'"]+['"]\s*$/gm, '')
  const encoded = Buffer.from(withoutImports).toString('base64')
  return import(`data:text/javascript;base64,${encoded}`)
}

test('turn clarification starts no polling and keeps action available', () => {
  const clarification = { id: 8, interaction: { status: 'pending' } }
  const state = reconcileTurnResult({ jobs: [], clarification })

  assert.deepEqual(state.jobs, [])
  assert.deepEqual(state.pollJobIds, [])
  assert.equal(state.clarification, clarification)
})

test('all jobs in a unified mutation response are merged and polled', () => {
  const jobs = [{ id: 1 }, { id: 2 }, { id: 3 }]
  const state = reconcileTurnResult({ jobs, job: { id: 99 } })

  assert.deepEqual(state.jobs, jobs)
  assert.deepEqual(state.pollJobIds, [1, 2, 3])
  assert.equal(state.clarification, null)
})

test('clarification-owned drafts never recover into the composer', () => {
  const restored = recoverComposerDrafts([
    { id: 1, asset_type: 'upload', status: 'draft', message_id: null },
    { id: 2, asset_type: 'upload', status: 'draft', message_id: 88 },
    { id: 3, asset_type: 'upload', status: 'attached', message_id: 89 },
  ])

  assert.deepEqual(restored.map(item => item.asset.id), [1])
})

test('only whitelisted business errors may expose backend copy', () => {
  for (const code of ['multi_output_limit', 'daily_limit_exceeded', 'attachment_unavailable']) {
    assert.equal(
      safeBusinessErrorMessage({ response: { data: { detail: { code, message: `safe:${code}` } } } }),
      `safe:${code}`,
    )
  }
  assert.equal(safeBusinessErrorMessage({ response: { data: { detail: {
    code: 'daily_limit_exceeded', message: '今日生成额度不足', meta: { remaining: 2, internal: 'ignored' },
  } } } }), '今日生成额度不足（今日剩余 2 次）')
  assert.equal(safeBusinessErrorMessage({ response: { data: { detail: {
    code: 'multi_output_limit', message: '请求数量过多', meta: { max_outputs: 4 },
  } } } }), '请求数量过多（最多 4 张）')
  assert.equal(safeBusinessErrorMessage({
    response: { data: { detail: { code: 'internal_hint', message: 'secret provider detail' } } },
  }), null)
  assert.equal(safeBusinessErrorMessage({ response: { data: { detail: 'raw detail' } } }), null)

  const requestSource = readFileSync(new URL('../src/api/request.js', import.meta.url), 'utf8')
  assert.match(requestSource, /error\.config\?\.suppressToast[\s\S]*?Promise\.reject\(error\)/)
})

test('action API posts the unified confirmation payload to the message route', () => {
  const source = readFileSync(new URL('../src/api/designImage.js', import.meta.url), 'utf8')
  assert.match(source, /export function resolveMessageAction\(sessionId, messageId, data\)/)
  assert.match(source, /`\/sessions\/\$\{sessionId\}\/messages\/\$\{messageId\}\/actions`/)
})

test('inline confirmation card keeps accessibility and motion contracts', () => {
  const source = readFileSync(new URL(
    '../src/views/design/image-studio/components/OutputModeConfirmation.vue', import.meta.url,
  ), 'utf8')

  assert.match(source, /<button[\s\S]*?type="button"/)
  assert.match(source, /一张[\s\S]*?拼版/)
  assert.match(source, /分别生成/)
  assert.match(source, /消耗 1 次/)
  assert.match(source, /消耗[^<]*\{\{[^}]*count[^}]*\}\}[^<]*次/)
  assert.match(source, /min-height:\s*44px/)
  assert.match(source, /animation:\s*confirmation-enter 180ms cubic-bezier\(0\.23, 1, 0\.32, 1\) both/)
  assert.match(source, /@media\s*\(hover:\s*hover\)\s*and\s*\(pointer:\s*fine\)/)
  assert.match(source, /@media\s*\(prefers-reduced-motion:\s*reduce\)/)
  assert.doesNotMatch(source, /<el-dialog|role="dialog"|transition\s*:\s*all\b/i)
  assert.match(source, /interaction\.status\s*===\s*['"]resolved['"]/)
  assert.match(source, /已选择：/)
  assert.match(source, /v-else class="mode-options"/)
  assert.match(source, /:disabled="submitting"/)
  assert.match(source, /interaction\.item_kind\s*===\s*['"]angle['"]/)
  assert.match(source, /标准角度：/)
  assert.match(source, /版本：/)
  assert.match(source, /同图对比版/)
})

test('empty state explains the default and multi-output confirmation', () => {
  const source = readFileSync(new URL(
    '../src/views/design/image-studio/components/MessageThread.vue', import.meta.url,
  ), 'utf8')
  assert.match(source, /默认生成一张；需要多张时会先确认输出方式和消耗次数。/)
  assert.doesNotMatch(source, /每轮只生成一张/)
})

test('message thread renders confirmation inline and emits a mode choice', () => {
  const source = readFileSync(new URL(
    '../src/views/design/image-studio/components/MessageThread.vue', import.meta.url,
  ), 'utf8')
  assert.match(source, /OutputModeConfirmation/)
  assert.match(source, /message\.interaction\?\.type\s*===\s*['"]output_mode_confirmation['"]/)
  assert.match(source, /emit\(['"]choose-output-mode['"]/)
})

test('studio composable reconciles create, resolve, and retry through jobs arrays', () => {
  const source = readFileSync(new URL(
    '../src/views/design/image-studio/composables/useImageStudio.js', import.meta.url,
  ), 'utf8')
  assert.match(source, /resolveMessageAction/)
  assert.match(source, /reconcileTurnResult/)
  assert.doesNotMatch(source, /result\.job\b/)
  const retryHandler = source.match(/async function retry[\s\S]*?(?=\n  function isConfirmationSubmitting)/)?.[0] || ''
  assert.match(retryHandler, /refreshConflictSession\(error,\s*job\.session_id,\s*refreshCurrentSession\)/)
  assert.match(source, /confirmationRequests\s*=\s*reactive\(new Set\(\)\)/)
  assert.match(source, /confirmationRequests\.has\(messageId\)/)
  const actionHandler = source.match(/async function chooseOutputMode[\s\S]*?(?=\n  function chooseBaseAsset)/)?.[0] || ''
  assert.match(actionHandler, /resolveMessageAction/)
  assert.doesNotMatch(actionHandler, /sendInFlight\.value\s*=/)
})

test('retry conflict refresh helper reloads only HTTP 409 sessions', async () => {
  const { refreshConflictSession } = await importStudioPureHelpers()
  const refreshed = []
  const reload = async sessionId => refreshed.push(sessionId)

  assert.equal(await refreshConflictSession({ response: { status: 409 } }, 71, reload), true)
  assert.equal(await refreshConflictSession({ response: { status: 422 } }, 72, reload), false)
  assert.equal(await refreshConflictSession(new Error('network'), 73, reload), false)
  assert.deepEqual(refreshed, [71])
})
