import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'
import { build } from 'vite'

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

const API_STUB_PREFIX = '__designImageApiTest_'
let apiImportSequence = 0

async function importDesignImageWithClient(client, suffix = '') {
  const source = readFileSync(new URL('../src/api/designImage.js', import.meta.url), 'utf8')
  const stubKey = `${API_STUB_PREFIX}${process.pid}_${++apiImportSequence}`
  const injected = source.replace(
    /import\s*\{\s*designImageClient\s*\}\s*from\s*['"]\.\/clients['"]/,
    `const { designImageClient } = globalThis[${JSON.stringify(stubKey)}]`,
  )
  assert.notEqual(injected, source)
  globalThis[stubKey] = { designImageClient: client }
  try {
    const encoded = Buffer.from(`${injected}\n${suffix}`).toString('base64')
    return await import(`data:text/javascript;base64,${encoded}#${stubKey}`)
  } finally {
    delete globalThis[stubKey]
  }
}

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

test('same-job late queued responses cannot reactivate a terminal job', () => {
  for (const status of ['succeeded', 'failed']) {
    const current = {
      activeJobId: null,
      jobs: [{ id: 41, status }],
    }
    const next = replaceActiveJob(current, { id: 41, status: 'queued' })

    assert.equal(next.activeJobId, null)
    assert.equal(next.jobs[0].status, status)
  }
})

test('a new job ID is active only while its status is active', () => {
  for (const status of ['queued', 'running']) {
    const next = replaceActiveJob(
      { activeJobId: 41, jobs: [{ id: 41, status: 'failed' }] },
      { id: 42, status },
    )
    assert.equal(next.activeJobId, 42)
  }
  for (const status of ['succeeded', 'failed']) {
    const next = replaceActiveJob(
      { activeJobId: 41, jobs: [{ id: 41, status: 'failed' }] },
      { id: 42, status },
    )
    assert.equal(next.activeJobId, null)
  }
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

test('object URL creation failure preserves the existing registered URL', () => {
  let shouldThrow = false
  const revoked = []
  const registry = createObjectUrlRegistry({
    createObjectURL() {
      if (shouldThrow) throw new Error('create failed')
      return 'blob:existing'
    },
    revokeObjectURL(url) {
      revoked.push(url)
    },
  })
  registry.create(1, {})
  shouldThrow = true

  assert.throws(() => registry.create(1, {}), /create failed/)
  assert.equal(registry.get(1), 'blob:existing')
  assert.deepEqual(revoked, [])
})

test('object URL revoke failures do not retain entries or stop bulk cleanup', () => {
  let sequence = 0
  const attempts = []
  const registry = createObjectUrlRegistry({
    createObjectURL() {
      sequence += 1
      return `blob:${sequence}`
    },
    revokeObjectURL(url) {
      attempts.push(url)
      if (url === 'blob:1') throw new Error('revoke failed')
    },
  })
  registry.create(1, {})
  registry.create(2, {})

  assert.doesNotThrow(() => registry.revokeAll())
  assert.deepEqual(attempts, ['blob:1', 'blob:2'])
  assert.equal(registry.get(1), null)
  assert.equal(registry.get(2), null)
  registry.revokeAll()
  assert.deepEqual(attempts, ['blob:1', 'blob:2'])
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

test('design image API resolves its real named import in an in-memory Vite build', async () => {
  const result = await build({
    configFile: fileURLToPath(new URL('../vite.config.js', import.meta.url)),
    logLevel: 'silent',
    build: {
      write: false,
      minify: false,
      rollupOptions: {
        input: fileURLToPath(new URL('../src/api/designImage.js', import.meta.url)),
      },
    },
  })
  assert.ok(result)
})

test('design image API stub is removed even when module initialization fails', async () => {
  await assert.rejects(
    importDesignImageWithClient({}, "throw new Error('module initialization failed')"),
    /module initialization failed/,
  )
  assert.equal(
    Object.keys(globalThis).some(key => key.startsWith(API_STUB_PREFIX)),
    false,
  )
})

test('design image API wrappers execute every route with data and request config intact', async () => {
  const calls = []
  const client = Object.fromEntries(['get', 'post', 'delete'].map(method => [
    method,
    (...args) => {
      const result = { call: calls.length }
      calls.push({ method, args, result })
      return result
    },
  ]))
  const api = await importDesignImageWithClient(client)

  const session = { title: 'campaign' }
  const params = { limit: 20, cursor: 'next' }
  const turn = { prompt: 'new poster', request_id: 'request-1' }
  const retry = { request_id: 'retry-1' }
  const usage = { owner_user_id: 7, status: 'failed' }
  const results = [
    api.getConfig(),
    api.createSession(session),
    api.listSessions(params),
    api.getSession(11),
    api.uploadAsset(11, 'image-file'),
    api.deleteAsset(31),
    api.createTurn(11, turn),
    api.getActiveJob(),
    api.getJob(41),
    api.retryJob(41, retry),
    api.getAssetBlob(31, { thumbnail: true, download: true }),
    api.getUsage(usage),
  ]
  assert.deepEqual(results, calls.map(call => call.result))
  assert.deepEqual(calls.map(({ method, args }) => [method, args[0]]), [
    ['get', '/config'],
    ['post', '/sessions'],
    ['get', '/sessions'],
    ['get', '/sessions/11'],
    ['post', '/sessions/11/assets'],
    ['delete', '/assets/31'],
    ['post', '/sessions/11/turns'],
    ['get', '/jobs/active'],
    ['get', '/jobs/41'],
    ['post', '/jobs/41/retry'],
    ['get', '/assets/31/content'],
    ['get', '/usage'],
  ])
  for (const callIndex of [0, 3, 5]) {
    assert.deepEqual(calls[callIndex].args[1], { showLoading: false })
  }
  assert.equal(calls[1].args[1], session)
  assert.deepEqual(calls[2].args[1], { params, showLoading: false })
  assert.equal(calls[4].args[1] instanceof FormData, true)
  assert.equal(calls[4].args[1].get('file'), 'image-file')
  assert.deepEqual(calls[4].args[2], { showLoading: false, suppressToast: true })
  assert.equal(calls[6].args[1], turn)
  assert.deepEqual(calls[6].args[2], { showLoading: false, suppressToast: true })
  for (const callIndex of [7, 8]) {
    assert.deepEqual(calls[callIndex].args[1], {
      showLoading: false,
      suppressToast: true,
      timeout: 20000,
    })
  }
  assert.equal(calls[9].args[1], retry)
  assert.deepEqual(calls[9].args[2], { showLoading: false, suppressToast: true })
  assert.deepEqual(calls[10].args[1], {
    showLoading: false,
    suppressToast: true,
    params: { thumbnail: true, download: true },
    responseType: 'blob',
  })
  assert.deepEqual(calls[11].args[1], { params: usage, showLoading: false })
})

test('design image studio is registered once with a lazy read-protected route', () => {
  const navigation = readFileSync(new URL('../src/config/navigation.js', import.meta.url), 'utf8')

  assert.equal((navigation.match(/path:\s*['"]\/design\/image-studio['"]/g) || []).length, 1)
  assert.match(navigation, /component:\s*\(\)\s*=>\s*import\(['"]@\/views\/design\/image-studio\/ImageStudio\.vue['"]\)/)
  assert.match(navigation, /permission:\s*['"]design_image:read['"]/)
  assert.match(navigation, /design:\s*\{[\s\S]*?title:\s*['"]设计中心['"]/)
})

test('design image studio files keep the phase-four layout and motion contract', () => {
  const files = [
    '../src/views/design/image-studio/ImageStudio.vue',
    '../src/views/design/image-studio/composables/useImageStudio.js',
    '../src/views/design/image-studio/composables/useJobPolling.js',
    '../src/views/design/image-studio/composables/useAssetObjectUrls.js',
    '../src/views/design/image-studio/components/ConversationSidebar.vue',
    '../src/views/design/image-studio/components/MessageThread.vue',
    '../src/views/design/image-studio/components/PromptComposer.vue',
    '../src/views/design/image-studio/components/GenerationCard.vue',
    '../src/views/design/image-studio/components/ImageLightbox.vue',
  ]
  const sources = files.map(file => ({ file, source: readFileSync(new URL(file, import.meta.url), 'utf8') }))

  for (const { file, source } of sources) {
    assert.doesNotMatch(source, /#[0-9a-f]{3,8}\b/i, `${file} contains a naked hex color`)
    assert.doesNotMatch(source, /transition\s*:\s*all\b/i, `${file} uses transition: all`)
    assert.doesNotMatch(source, /\bease-in\b/i, `${file} uses ease-in`)
    assert.doesNotMatch(source, /\.glass-card\b/, `${file} introduces the forbidden glass-card class`)
    assert.ok(source.split(/\r?\n/).length < 500, `${file} must remain below 500 lines`)
  }

  const joined = sources.map(item => item.source).join('\n')
  assert.match(joined, /prefers-reduced-motion:\s*reduce/)
  assert.match(joined, /@media\s*\(hover:\s*hover\)\s*and\s*\(pointer:\s*fine\)/)
  assert.doesNotMatch(joined, /\bsetInterval\s*\(/)
  assert.match(joined, /show-list="false"/)
  assert.match(joined, /padding-bottom:\s*max\([^)]*env\(safe-area-inset-bottom\)/)
  assert.match(joined, /scale\(0\.97\)/)
  assert.match(joined, /cubic-bezier\(0\.23,\s*1,\s*0\.32,\s*1\)/)
})

test('polling and object URL composables expose snapshot guards and centralized cleanup', () => {
  const polling = readFileSync(
    new URL('../src/views/design/image-studio/composables/useJobPolling.js', import.meta.url),
    'utf8',
  )
  const assets = readFileSync(
    new URL('../src/views/design/image-studio/composables/useAssetObjectUrls.js', import.meta.url),
    'utf8',
  )

  assert.match(polling, /setTimeout\s*\(/)
  assert.match(polling, /pollBusy/)
  assert.match(polling, /pollGeneration/)
  assert.match(polling, /sessionIdSnapshot/)
  assert.match(polling, /jobIdSnapshot/)
  assert.match(polling, /stopPolling/)
  assert.doesNotMatch(polling, /setInterval\s*\(/)
  assert.match(assets, /batchToken/)
  assert.match(assets, /revokeAll/)
  assert.match(assets, /response\.data/)

  const studio = readFileSync(
    new URL('../src/views/design/image-studio/composables/useImageStudio.js', import.meta.url),
    'utf8',
  )
  assert.match(studio, /advanceJob\(jobSnapshots\.get\(job\.id\),\s*job\)/)
  assert.match(studio, /currentSession\.value\s*=\s*null[\s\S]*messages\.value\s*=\s*\[\][\s\S]*assets\.value\s*=\s*\[\][\s\S]*jobs\.value\s*=\s*\[\]/)
})
