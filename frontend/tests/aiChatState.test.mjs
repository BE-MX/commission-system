import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

import {
  STARTERS,
  createInitialState,
  createSseParser,
  isComposerSubmit,
  reduceChatState,
  requestId,
} from '../src/views/design/ai-chat/state.js'
import * as chatState from '../src/views/design/ai-chat/state.js'

function readSource(relativePath) {
  try {
    return readFileSync(new URL(relativePath, import.meta.url), 'utf8')
  } catch {
    return ''
  }
}

function routeEntry(source, path) {
  const start = source.indexOf(`path: '${path}'`)
  if (start === -1) return ''
  const next = source.indexOf("\n  {", start + 1)
  return source.slice(start, next === -1 ? source.length : next)
}

const event = (generation, name, data) => ({
  type: 'stream-event',
  generation,
  event: { event: name, data },
})

function bodyFromChunks(chunks, readError = null) {
  const encoded = chunks.map(chunk => new TextEncoder().encode(chunk))
  let index = 0
  return {
    getReader() {
      return {
        async read() {
          if (index < encoded.length) return { done: false, value: encoded[index++] }
          if (readError) throw readError
          return { done: true, value: undefined }
        },
        releaseLock() {},
      }
    },
  }
}

test('provides four fixed starters that only fill the composer', () => {
  assert.deepEqual(STARTERS.map(item => item.title), [
    '客户需求分析',
    '产品方案',
    '营销推广方案',
    '邮件与沟通话术',
  ])

  const next = reduceChatState(createInitialState(), {
    type: 'apply-starter',
    starter: STARTERS[0],
  })
  assert.match(next.prompt, /客户需求/)
  assert.equal(next.streaming, false)
  assert.deepEqual(next.messages, [])
})

test('exposes one AI workspace menu with permission-safe image and chat routes', () => {
  const navigation = readSource('../src/config/navigation.js')
  const visibleMenus = navigation.match(/menu:\s*\{[^}]*title:\s*['"]AI 工作台['"][^}]*\}/gs) || []
  const imageRoute = routeEntry(navigation, '/design/image-studio')
  const chatRoute = routeEntry(navigation, '/design/ai-chat')

  assert.equal(visibleMenus.length, 1)
  assert.match(imageRoute, /anyPermission:\s*\[\s*['"]design_image:read['"]\s*,\s*['"]ai_chat:read['"]\s*\]/)
  assert.doesNotMatch(imageRoute, /\n\s*permission:\s*['"]design_image:read['"]/)
  assert.match(chatRoute, /name:\s*['"]DesignAiChat['"]/)
  assert.match(chatRoute, /permission:\s*['"]ai_chat:read['"]/)
  assert.match(chatRoute, /hideInMenu:\s*true/)
  assert.doesNotMatch(chatRoute, /\n\s*menu:\s*\{/)
})

test('shares route-backed workspace tabs across both AI pages', () => {
  const tabs = readSource('../src/views/design/ai-workspace/AiWorkspaceTabs.vue')
  const imagePage = readSource('../src/views/design/image-studio/ImageStudio.vue')
  const chatPage = readSource('../src/views/design/ai-chat/AiChat.vue')

  assert.match(tabs, /role="tablist"/)
  assert.equal((tabs.match(/role="tab"/g) || []).length, 2)
  assert.match(tabs, /aria-selected/)
  assert.match(tabs, /DesignImageStudio/)
  assert.match(tabs, /DesignAiChat/)
  assert.match(imagePage, /<AiWorkspaceTabs\s*\/>/)
  assert.match(chatPage, /<AiWorkspaceTabs\s*\/>/)
})

test('keeps the visible AI workspace menu active on the hidden chat route', () => {
  const navigation = readSource('../src/config/navigation.js')
  const router = readSource('../src/router/index.js')
  const layout = readSource('../src/views/layout/MainLayout.vue')
  const chatRoute = routeEntry(navigation, '/design/ai-chat')

  assert.match(chatRoute, /activeMenu:\s*['"]\/design\/image-studio['"]/)
  assert.match(router, /activeMenu:\s*entry\.activeMenu/)
  assert.match(layout, /:default-active="route\.meta\.activeMenu \|\| route\.path"/)
})

test('starter cards fill without sending and Markdown is sanitized before injection', () => {
  const starters = readSource('../src/views/design/ai-chat/components/StarterCards.vue')
  const thread = readSource('../src/views/design/ai-chat/components/ChatThread.vue')

  assert.match(starters, /emit\(['"]select['"]/)
  assert.doesNotMatch(starters, /emit\(['"](?:send|submit)['"]/)
  assert.match(thread, /DOMPurify\.sanitize\(marked\.parse\(raw\)\)/)
  assert.match(thread, /navigator\.clipboard\.writeText\(message\.content/)
})

test('isolates terminal detail refresh failures from the completed stream result', () => {
  const composable = readSource('../src/views/design/ai-chat/composables/useAiChat.js')

  assert.match(composable, /async function refreshAfterStream\(/)
  assert.match(composable, /await refreshAfterStream\(sessionId, generation, expectedWorkspace\)/)
})

test('reloads non-abort failures only while the stream and session are current', () => {
  const composable = readSource('../src/views/design/ai-chat/composables/useAiChat.js')

  assert.match(composable, /async function reloadFailedSession\(sessionId, generation, expectedWorkspace\)/)
  assert.match(composable, /generation !== streamGeneration[\s\S]*expectedWorkspace !== workspaceGeneration[\s\S]*currentSessionId\.value !== sessionId/)
  assert.match(composable, /error\.value = \{ message,[^}]*\}[\s\S]*await reloadFailedSession\(sessionId, generation, expectedWorkspace\)/)
})

test('parses split frames, CRLF, comments, and multiple data lines', () => {
  const parser = createSseParser()
  assert.deepEqual(parser.push('event: delta\r\ndata: {"text":"方'), [])
  assert.deepEqual(parser.push('案"}\r\n\r\n: keep-alive\n\nevent: heartbeat\ndata: {\n'),
    [{ event: 'delta', data: { text: '方案' } }])
  assert.deepEqual(parser.push('data: "status":"streaming"}\n\n'), [
    { event: 'heartbeat', data: { status: 'streaming' } },
  ])
})

test('does not report a half frame and safely converts malformed JSON to error', () => {
  const parser = createSseParser()
  assert.deepEqual(parser.push('event: delta\ndata: {"text":'), [])
  assert.deepEqual(parser.flush(), [{
    event: 'error',
    data: { code: 'invalid_sse_data', message: '模型返回了无法解析的消息' },
  }])
})

test('accepts done and error terminal events emitted by parser flush', async () => {
  for (const terminal of ['done', 'error']) {
    const received = []
    const data = terminal === 'done'
      ? { status: 'completed' }
      : { code: 'upstream_unavailable', message: '请重试' }
    await chatState.consumeSseStream(bodyFromChunks([
      'event: heartbeat\ndata: {"status":"streaming"}\n\n',
      `event: ${terminal}\ndata: ${JSON.stringify(data)}`,
    ]), { onEvent: frame => received.push(frame) })
    assert.equal(received.at(-1).event, terminal)
  }
})

test('rejects an unexpected EOF after dispatching partial frames', async () => {
  const received = []
  await assert.rejects(
    chatState.consumeSseStream(bodyFromChunks([
      'event: meta\ndata: {"assistant_message_id":31}\n\n',
      'event: delta\ndata: {"text":"部分回答"}\n\n',
    ]), { onEvent: frame => received.push(frame) }),
    /连接意外中断，请重试/,
  )
  assert.deepEqual(received.map(frame => frame.event), ['meta', 'delta'])
})

test('preserves AbortError instead of converting it to incomplete stream failure', async () => {
  const abortError = new Error('user stopped')
  abortError.name = 'AbortError'
  await assert.rejects(
    chatState.consumeSseStream(bodyFromChunks([], abortError)),
    error => error === abortError,
  )
})

test('applies meta, delta, heartbeat, done, and error only to the active generation', () => {
  let state = reduceChatState(createInitialState({ activeSessionId: 7 }), {
    type: 'start-stream',
    message: { id: 'pending', role: 'assistant', content: '', status: 'streaming' },
  })
  const generation = state.streamGeneration

  state = reduceChatState(state, event(generation, 'meta', {
    session_id: 7,
    assistant_message_id: 31,
    status: 'streaming',
  }))
  state = reduceChatState(state, event(generation, 'heartbeat', { status: 'streaming' }))
  assert.equal(state.lastHeartbeat.status, 'streaming')

  state = reduceChatState(state, event(generation, 'delta', { text: '方案' }))
  assert.equal(state.messages.at(-1).id, 31)
  assert.equal(state.messages.at(-1).content, '方案')

  const stale = reduceChatState(state, event(generation - 1, 'delta', { text: '过期' }))
  assert.strictEqual(stale, state)

  state = reduceChatState(state, event(generation, 'done', { status: 'completed', total_tokens: 12 }))
  assert.equal(state.streaming, false)
  assert.equal(state.messages.at(-1).status, 'completed')
  assert.equal(state.streamSummary.total_tokens, 12)

  state = reduceChatState(state, { type: 'start-stream' })
  state = reduceChatState(state, event(state.streamGeneration, 'meta', {
    session_id: 7,
    assistant_message_id: 32,
    status: 'streaming',
  }))
  state = reduceChatState(state, event(state.streamGeneration, 'error', {
    code: 'rate_limited',
    message: '当前请求较多，请稍后重试',
  }))
  assert.equal(state.streaming, false)
  assert.equal(state.messages.at(-1).status, 'failed')
  assert.match(state.error.message, /请稍后/)
})

test('keeps a turn pending until meta materializes real message ids once', () => {
  let state = reduceChatState(createInitialState({ activeSessionId: 7 }), {
    type: 'start-stream',
    pending: {
      userMessage: { role: 'user', content: '客户需要自然发际线' },
      assistantMessage: { role: 'assistant', content: '', status: 'streaming' },
    },
  })
  const generation = state.streamGeneration

  assert.equal(state.streaming, true)
  assert.deepEqual(state.messages, [])
  assert.equal(state.pendingTurn.userMessage.content, '客户需要自然发际线')

  state = reduceChatState(state, event(generation, 'meta', {
    session_id: 7,
    user_message_id: 30,
    assistant_message_id: 31,
    status: 'streaming',
  }))
  assert.deepEqual(state.messages.map(message => message.id), [30, 31])
  assert.equal(state.pendingTurn, null)

  state = reduceChatState(state, event(generation, 'meta', {
    session_id: 7,
    user_message_id: 30,
    assistant_message_id: 31,
    status: 'streaming',
  }))
  assert.deepEqual(state.messages.map(message => message.id), [30, 31])
})

test('preserves composer drafts when a stream fails before meta', () => {
  const attachment = { id: 41, original_name: 'brief.pdf' }
  let state = reduceChatState(createInitialState({
    activeSessionId: 7,
    prompt: 'keep this draft',
    draftAttachments: [attachment],
  }), {
    type: 'start-stream',
    pending: {
      userMessage: { role: 'user', content: 'keep this draft' },
      assistantMessage: { role: 'assistant', content: '', status: 'streaming' },
      composerSnapshot: { prompt: 'keep this draft', attachmentIds: [41] },
    },
  })

  state = reduceChatState(state, event(state.streamGeneration, 'error', {
    code: 'network_error',
    message: 'retry',
  }))
  assert.equal(state.prompt, 'keep this draft')
  assert.deepEqual(state.draftAttachments, [attachment])

  const composable = readSource('../src/views/design/ai-chat/composables/useAiChat.js')
  assert.doesNotMatch(composable, /if \(!retryMessageId\) \{\s*prompt\.value = ''\s*draftAttachments\.value = \[\]/)
})

test('clears an unchanged composer only after current meta acknowledgement', () => {
  let state = reduceChatState(createInitialState({
    activeSessionId: 7,
    prompt: 'send this draft',
    draftAttachments: [{ id: 42 }],
  }), {
    type: 'start-stream',
    pending: {
      userMessage: { role: 'user', content: 'send this draft' },
      assistantMessage: { role: 'assistant', content: '', status: 'streaming' },
      composerSnapshot: { prompt: 'send this draft', attachmentIds: [42] },
    },
  })

  assert.equal(state.prompt, 'send this draft')
  assert.deepEqual(state.draftAttachments.map(item => item.id), [42])
  state = reduceChatState(state, event(state.streamGeneration, 'meta', {
    session_id: 7,
    user_message_id: 40,
    assistant_message_id: 41,
    status: 'streaming',
  }))
  assert.equal(state.prompt, '')
  assert.deepEqual(state.draftAttachments, [])
})

test('stale meta and current meta never clear newer composer input', () => {
  let state = reduceChatState(createInitialState({
    activeSessionId: 7,
    prompt: 'original draft',
    draftAttachments: [{ id: 43 }],
  }), {
    type: 'start-stream',
    pending: {
      userMessage: { role: 'user', content: 'original draft' },
      assistantMessage: { role: 'assistant', content: '', status: 'streaming' },
      composerSnapshot: { prompt: 'original draft', attachmentIds: [43] },
    },
  })
  const generation = state.streamGeneration
  state = reduceChatState(state, { type: 'set-prompt', prompt: 'new input' })

  const stale = reduceChatState(state, event(generation - 1, 'meta', {
    session_id: 7,
    user_message_id: 50,
    assistant_message_id: 51,
  }))
  assert.strictEqual(stale, state)

  state = reduceChatState(state, event(generation, 'meta', {
    session_id: 7,
    user_message_id: 50,
    assistant_message_id: 51,
  }))
  assert.equal(state.prompt, 'new input')
  assert.deepEqual(state.draftAttachments.map(item => item.id), [43])
})

test('stream reconciliation reloads messages without replacing live composer drafts', () => {
  const composable = readSource('../src/views/design/ai-chat/composables/useAiChat.js')

  assert.match(composable, /loadDetail\(sessionId, expectedWorkspace, generation, true\)/)
  assert.match(composable, /loadDetail\(sessionId, expectedWorkspace, stoppedGeneration, true\)/)
})

test('stop invalidates the active stream and retry appends a new answer', () => {
  const initial = createInitialState({
    messages: [{ id: 8, role: 'assistant', content: '旧回答', status: 'failed' }],
  })
  let streaming = reduceChatState(initial, { type: 'start-stream' })
  streaming = reduceChatState(streaming, event(streaming.streamGeneration, 'meta', {
    assistant_message_id: 9,
    status: 'streaming',
  }))
  const stopped = reduceChatState(streaming, { type: 'stop-stream' })
  assert.equal(stopped.streaming, false)
  assert.equal(stopped.messages.at(-1).status, 'stopped')
  assert.equal(stopped.streamGeneration, streaming.streamGeneration + 1)

  let retried = reduceChatState(stopped, {
    type: 'start-retry',
    messageId: 8,
    message: { id: 'retry-pending', role: 'assistant', content: '', status: 'streaming' },
  })
  assert.equal(retried.messages.length, 2)
  retried = reduceChatState(retried, event(retried.streamGeneration, 'meta', {
    assistant_message_id: 10,
    status: 'streaming',
  }))
  assert.equal(retried.messages.length, 3)
  assert.equal(retried.messages[0].content, '旧回答')
  assert.equal(retried.messages.at(-1).retry_of_message_id, 8)
})

test('limits drafts to five and resets transient state on session switch', () => {
  let state = createInitialState({ activeSessionId: 1, prompt: '未发送' })
  for (let id = 1; id <= 6; id += 1) {
    state = reduceChatState(state, { type: 'add-draft-attachment', attachment: { id } })
  }
  assert.deepEqual(state.draftAttachments.map(item => item.id), [1, 2, 3, 4, 5])

  state = reduceChatState(state, { type: 'switch-session', sessionId: 2 })
  assert.equal(state.activeSessionId, 2)
  assert.equal(state.prompt, '')
  assert.deepEqual(state.messages, [])
  assert.deepEqual(state.draftAttachments, [])
  assert.equal(state.streaming, false)
})

test('composer submit helper respects IME and keyboard semantics', () => {
  assert.equal(isComposerSubmit({ key: 'Enter', isComposing: false, shiftKey: false }), true)
  assert.equal(isComposerSubmit({ key: 'Enter', isComposing: true, shiftKey: false }), false)
  assert.equal(isComposerSubmit({ key: 'Enter', isComposing: false, shiftKey: true }), false)
  assert.equal(isComposerSubmit({ key: 'Space', isComposing: false, shiftKey: false }), false)
})

test('request ids satisfy the backend idempotency format', () => {
  const first = requestId()
  const second = requestId()
  assert.match(first, /^[A-Za-z0-9_-]{8,64}$/)
  assert.notEqual(first, second)
})

test('API source uses the shared client, complete routes, and native fetch streaming contract', () => {
  const clients = readFileSync(new URL('../src/api/clients.js', import.meta.url), 'utf8')
  const api = readFileSync(new URL('../src/api/aiChat.js', import.meta.url), 'utf8')
  const state = readFileSync(new URL('../src/views/design/ai-chat/state.js', import.meta.url), 'utf8')

  assert.match(clients, /aiChatClient\s*=\s*createApiClient\(\{\s*baseURL:\s*['"]\/api\/ai-chat['"],\s*timeout:\s*120000\s*\}\)/)
  assert.match(api, /aiChatClient\.(?:get|post|delete)/)
  for (const route of [
    "get('/config')",
    "post('/sessions'",
    "get('/sessions'",
    'get(`/sessions/${sessionId}`',
    'post(`/sessions/${sessionId}/attachments`',
    'delete(`/attachments/${attachmentId}`',
    'get(`/attachments/${attachmentId}/content`',
  ]) {
    assert.ok(api.includes(route), `${route} should use aiChatClient`)
  }
  assert.match(api, /new FormData\(\)/)
  assert.doesNotMatch(api, /multipart\/form-data/)
  assert.match(api, /responseType:\s*['"]blob['"]/)
  assert.match(api, /export async function streamTurn/)
  assert.match(api, /export async function streamRetry/)
  assert.match(api, /consumeSseStream\(response\.body,\s*\{ onEvent \}\)/)
  assert.match(state, /TextDecoder\([^)]*\)/)
  assert.match(state, /stream:\s*true/)
  assert.match(api, /Accept:\s*['"]text\/event-stream['"]/)
  assert.match(api, /['"]Content-Type['"]:\s*['"]application\/json['"]/)
  assert.match(api, /contentType\.toLowerCase\(\)\.includes\(['"]text\/event-stream['"]\)/)
  assert.match(api, /response\.json\(\)/)
  assert.match(api, /getAccessToken\(\)/)
  assert.match(api, /clearAuthState\(\)/)
  assert.doesNotMatch(api, /catch\s*\([^)]*\)\s*\{[^}]*AbortError/s)
  assert.doesNotMatch(api, /axios\.create|createApiClient/)
})
