import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  acceptConversationResponse,
  advanceJob,
  canStartSend,
  canStartUpload,
  createObjectUrlRegistry,
  replaceActiveJob,
  restoreActiveJob,
  selectBaseAsset,
  upsertAttachment,
} from '../src/views/design/image-studio/state.js'

test('job status advances monotonically and terminal states cannot be overwritten', () => {
  const queued = { id: 7, status: 'queued', note: 'queued' }
  const running = advanceJob(queued, { id: 7, status: 'running', note: 'running' })
  assert.equal(running.status, 'running')

  const staleQueued = advanceJob(running, { id: 7, status: 'queued', note: 'stale' })
  assert.deepEqual(staleQueued, running)

  const succeeded = advanceJob(running, { id: 7, status: 'succeeded', note: 'done' })
  assert.equal(succeeded.status, 'succeeded')
  assert.deepEqual(
    advanceJob(succeeded, { id: 7, status: 'failed', note: 'late failure' }),
    succeeded,
  )
})

test('conversation generation accepts only the currently active response', () => {
  assert.equal(acceptConversationResponse(4, 4), true)
  assert.equal(acceptConversationResponse(5, 4), false)
})

test('send guard rejects duplicate sends, uploads, and active generation jobs', () => {
  assert.equal(canStartSend({}), true)
  assert.equal(canStartSend({ sendInFlight: true }), false)
  assert.equal(canStartSend({ uploadInFlight: true }), false)
  assert.equal(canStartSend({ activeJob: { status: 'queued' } }), false)
  assert.equal(canStartSend({ activeJob: { status: 'running' } }), false)
  assert.equal(canStartSend({ activeJob: { status: 'failed' } }), true)
})

test('upload guard rejects duplicate uploads and send races', () => {
  assert.equal(canStartUpload({}), true)
  assert.equal(canStartUpload({ uploadInFlight: true }), false)
  assert.equal(canStartUpload({ sendInFlight: true }), false)
})

test('concurrent attachment completion updates immutable snapshots without losing items', () => {
  let items = []
  items = upsertAttachment(items, 'upload-a', { status: 'uploading', name: 'a.png' })
  items = upsertAttachment(items, 'upload-b', { status: 'uploading', name: 'b.png' })
  items = upsertAttachment(items, 'upload-b', { status: 'ready', assetId: 22 })
  items = upsertAttachment(items, 'upload-a', { status: 'ready', assetId: 11 })

  assert.deepEqual(items, [
    { uploadId: 'upload-a', status: 'ready', name: 'a.png', assetId: 11 },
    { uploadId: 'upload-b', status: 'ready', name: 'b.png', assetId: 22 },
  ])
})

test('base asset selection stores only the explicitly selected asset ID', () => {
  assert.equal(selectBaseAsset({ id: 31 }), 31)
  assert.equal(selectBaseAsset(null), null)
  assert.equal(selectBaseAsset({}), null)
})

test('active job restoration ignores completed jobs', () => {
  assert.deepEqual(restoreActiveJob({ id: 1, status: 'queued' }), { id: 1, status: 'queued' })
  assert.deepEqual(restoreActiveJob({ id: 2, status: 'running' }), { id: 2, status: 'running' })
  assert.equal(restoreActiveJob({ id: 3, status: 'succeeded' }), null)
  assert.equal(restoreActiveJob({ id: 4, status: 'failed' }), null)
  assert.equal(restoreActiveJob(null), null)
})

test('retry replaces the active job ID while preserving prior job history', () => {
  const current = {
    activeJobId: 41,
    jobs: [{ id: 41, status: 'failed' }],
  }
  const next = replaceActiveJob(current, { id: 42, status: 'queued', retry_of_job_id: 41 })

  assert.equal(next.activeJobId, 42)
  assert.deepEqual(next.jobs.map(job => job.id), [41, 42])
  assert.deepEqual(current.jobs.map(job => job.id), [41])
})

test('object URL registry revokes one, all, replacements, and repeated cleanup safely', () => {
  let sequence = 0
  const revoked = []
  const urlApi = {
    createObjectURL() {
      sequence += 1
      return `blob:test-${sequence}`
    },
    revokeObjectURL(url) {
      revoked.push(url)
    },
  }
  const registry = createObjectUrlRegistry(urlApi)

  assert.equal(registry.create(1, {}), 'blob:test-1')
  assert.equal(registry.create(2, {}), 'blob:test-2')
  assert.equal(registry.create(1, {}), 'blob:test-3')
  assert.deepEqual(revoked, ['blob:test-1'])
  assert.equal(registry.get(1), 'blob:test-3')

  registry.revoke(1)
  registry.revoke(1)
  registry.revokeAll()
  registry.revokeAll()
  assert.deepEqual(revoked, ['blob:test-1', 'blob:test-3', 'blob:test-2'])
})

test('design image API uses the registered shared client', () => {
  const clientsSource = readFileSync(new URL('../src/api/clients.js', import.meta.url), 'utf8')
  const apiSource = readFileSync(new URL('../src/api/designImage.js', import.meta.url), 'utf8')

  assert.match(
    clientsSource,
    /designImageClient\s*=\s*createApiClient\(\{\s*baseURL:\s*['"]\/api\/design-image['"],\s*timeout:\s*300000\s*\}\)/,
  )
  assert.match(apiSource, /import\s*\{\s*designImageClient\s*\}\s*from\s*['"]\.\/clients['"]/)
  assert.doesNotMatch(apiSource, /axios\.create/)
})

test('design image API exposes every backend route', () => {
  const source = readFileSync(new URL('../src/api/designImage.js', import.meta.url), 'utf8')
  for (const expected of [
    /\.get\(\s*['"]\/config['"]/,
    /\.post\(\s*['"]\/sessions['"]/,
    /\.get\(\s*['"]\/sessions['"]/,
    /\.get\(\s*`\/sessions\/\$\{sessionId\}`/,
    /\.post\(\s*`\/sessions\/\$\{sessionId\}\/assets`/,
    /\.delete\(\s*`\/assets\/\$\{assetId\}`/,
    /\.post\(\s*`\/sessions\/\$\{sessionId\}\/turns`/,
    /\.get\(\s*['"]\/jobs\/active['"]/,
    /\.get\(\s*`\/jobs\/\$\{jobId\}`/,
    /\.post\(\s*`\/jobs\/\$\{jobId\}\/retry`/,
    /\.get\(\s*`\/assets\/\$\{assetId\}\/content`/,
    /\.get\(\s*['"]\/usage['"]/,
  ]) {
    assert.match(source, expected)
  }
})

test('long task API calls are silent and asset content is an authenticated blob', () => {
  const source = readFileSync(new URL('../src/api/designImage.js', import.meta.url), 'utf8')

  assert.match(source, /const SILENT_REQUEST = \{ showLoading: false, suppressToast: true \}/)
  assert.match(source, /new FormData\(\)/)
  assert.match(source, /form\.append\(['"]file['"], file\)/)
  assert.match(source, /responseType:\s*['"]blob['"]/)
  assert.match(source, /params:\s*\{\s*thumbnail,\s*download\s*\}/)
})
