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
  composePrompt,
  createObjectUrlRegistry,
  groupSessionsByDayHalf,
  missingPromptParams,
  replaceActiveJob,
  restoreActiveJob,
  restoreActiveJobs,
  selectBaseAsset,
  selectSessionActiveJob,
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

test('concurrent sessions restore all active jobs and resolve per-session guards', () => {
  const restored = restoreActiveJobs([
    { id: 1, session_id: 11, status: 'queued' },
    { id: 2, session_id: 22, status: 'running' },
    { id: 3, session_id: 33, status: 'succeeded' },
  ])
  assert.deepEqual(restored.map(job => job.id), [1, 2])
  assert.deepEqual(restoreActiveJobs(undefined), [])

  const activeJobs = new Map(restored.map(job => [job.id, job]))
  assert.equal(selectSessionActiveJob(activeJobs, 11)?.id, 1)
  assert.equal(selectSessionActiveJob(activeJobs, 22)?.id, 2)
  assert.equal(selectSessionActiveJob(activeJobs, 33), null)
  assert.equal(selectSessionActiveJob(activeJobs, null), null)

  // 发送闸只看当前会话的进行中任务：别的会话在生成不阻塞本会话
  assert.equal(canStartSend({ activeJob: selectSessionActiveJob(activeJobs, 11) }), false)
  assert.equal(canStartSend({ activeJob: selectSessionActiveJob(activeJobs, 33) }), true)
})

test('prompt library composes templates and reports missing params', () => {
  const template = {
    content: '在{scene}拍{style}风格，保留主体',
    options: [
      { key: 'scene', label: '场景', choices: ['沙龙', '街拍'] },
      { key: 'style', label: '风格', choices: ['暖调', '冷调'] },
    ],
  }
  assert.equal(composePrompt(template, { scene: '沙龙', style: '暖调' }), '在沙龙拍暖调风格，保留主体')
  assert.equal(composePrompt(template, { scene: '街拍' }), '在街拍拍{style}风格，保留主体')
  assert.equal(composePrompt(template), '在{scene}拍{style}风格，保留主体')
  assert.deepEqual(missingPromptParams(template, { scene: '沙龙' }), ['style'])
  assert.deepEqual(missingPromptParams(template, { scene: '沙龙', style: '暖调' }), [])
  assert.deepEqual(missingPromptParams({ content: '无参数模板', options: [] }, {}), [])
  assert.deepEqual(missingPromptParams(null), [])
})

test('sidebar sessions group by local day half with most recent on top', () => {
  // 用本地时间构造、走 UTC 往返，保证任何时区下结果一致
  const stamp = (year, month, day, hour) => new Date(year, month - 1, day, hour).toISOString().slice(0, -1)
  const groups = groupSessionsByDayHalf([
    { id: 1, updated_at: stamp(2026, 8, 5, 9) },
    { id: 2, updated_at: stamp(2026, 8, 6, 13) },
    { id: 3, updated_at: stamp(2026, 8, 5, 15) },
    { id: 4, updated_at: stamp(2026, 8, 6, 10) },
    { id: 5, updated_at: null, created_at: null },
  ])
  assert.deepEqual(
    groups.map(group => group.label),
    ['2026-08-06 下午', '2026-08-06 上午', '2026-08-05 下午', '2026-08-05 上午', '更早'],
  )
  assert.deepEqual(groups.map(group => group.items.map(session => session.id)), [[2], [4], [3], [1], [5]])

  // 无 updated_at 时回退 created_at；正午 12 点整归入下午
  const fallback = groupSessionsByDayHalf([{ id: 9, created_at: stamp(2026, 8, 4, 12) }])
  assert.equal(fallback[0].label, '2026-08-04 下午')
  assert.deepEqual(groupSessionsByDayHalf(undefined), [])
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
  const client = Object.fromEntries(['get', 'post', 'put', 'delete'].map(method => [
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
    api.getActiveJobs(),
    api.getJob(41),
    api.retryJob(41, retry),
    api.getAssetBlob(31, { thumbnail: true, download: true }),
    api.getUsage(usage),
    api.listPromptTemplates({ includeInactive: true }),
    api.seedPromptTemplates(),
    api.listLibraryAssets('private'),
    api.uploadLibraryAsset('private', '我的图', 'image-file'),
    api.deleteLibraryAsset(51),
    api.cloneLibraryAsset(51, 11),
    api.getLibraryAssetBlob(51, { thumbnail: true }),
    api.createPromptTemplate(turn),
    api.updatePromptTemplate(61, turn),
    api.deletePromptTemplate(61),
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
    ['get', '/prompt-templates'],
    ['post', '/prompt-templates/seed'],
    ['get', '/library-assets'],
    ['post', '/library-assets'],
    ['delete', '/library-assets/51'],
    ['post', '/library-assets/51/clone'],
    ['get', '/library-assets/51/content'],
    ['post', '/prompt-templates'],
    ['put', '/prompt-templates/61'],
    ['delete', '/prompt-templates/61'],
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
  assert.deepEqual(calls[12].args[1], { params: { include_inactive: true }, showLoading: false })
  assert.deepEqual(calls[13].args[2], { showLoading: false, suppressToast: true })
  assert.deepEqual(calls[14].args[1], { params: { scope: 'private' }, showLoading: false })
  assert.equal(calls[15].args[1] instanceof FormData, true)
  assert.equal(calls[15].args[1].get('file'), 'image-file')
  assert.equal(calls[15].args[1].get('scope'), 'private')
  assert.deepEqual(calls[16].args[1], { showLoading: false })
  assert.deepEqual(calls[17].args[1], { session_id: 11 })
  assert.deepEqual(calls[18].args[1], {
    showLoading: false,
    suppressToast: true,
    params: { thumbnail: true },
    responseType: 'blob',
  })
  assert.equal(calls[19].args[1], turn)
  assert.deepEqual(calls[19].args[2], { showLoading: false, suppressToast: true })
  assert.equal(calls[20].args[1], turn)
  assert.deepEqual(calls[20].args[2], { showLoading: false, suppressToast: true })
  assert.deepEqual(calls[21].args[1], { showLoading: false })
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
    '../src/views/design/image-studio/composables/useLibraryObjectUrls.js',
    '../src/views/design/image-studio/components/ConversationSidebar.vue',
    '../src/views/design/image-studio/components/MessageThread.vue',
    '../src/views/design/image-studio/components/PromptComposer.vue',
    '../src/views/design/image-studio/components/GenerationCard.vue',
    '../src/views/design/image-studio/components/ImageLightbox.vue',
    '../src/views/design/image-studio/components/PromptLibraryDialog.vue',
    '../src/views/design/image-studio/components/PromptTemplateManagerDialog.vue',
    '../src/views/design/image-studio/components/ReferenceLibraryDialog.vue',
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
  assert.match(polling, /activeSnapshot/)
  assert.match(polling, /onTick/)
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
