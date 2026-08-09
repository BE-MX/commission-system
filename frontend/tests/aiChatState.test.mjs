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

const event = (generation, name, data) => ({
  type: 'stream-event',
  generation,
  event: { event: name, data },
})

test('provides four fixed starters that only fill the composer', () => {
  assert.deepEqual(STARTERS.map(item => item.title), [
    '客户需求梳理',
    '产品方案',
    '营销文案',
    '数据分析',
  ])

  const next = reduceChatState(createInitialState(), {
    type: 'apply-starter',
    starter: STARTERS[0],
  })
  assert.match(next.prompt, /客户需求/)
  assert.equal(next.streaming, false)
  assert.deepEqual(next.messages, [])
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
  state = reduceChatState(state, event(state.streamGeneration, 'error', {
    code: 'rate_limited',
    message: '当前请求较多，请稍后重试',
  }))
  assert.equal(state.streaming, false)
  assert.equal(state.messages.at(-1).status, 'failed')
  assert.match(state.error.message, /请稍后/)
})

test('stop invalidates the active stream and retry appends a new answer', () => {
  const initial = createInitialState({
    messages: [{ id: 8, role: 'assistant', content: '旧回答', status: 'failed' }],
  })
  const streaming = reduceChatState(initial, { type: 'start-stream' })
  const stopped = reduceChatState(streaming, { type: 'stop-stream' })
  assert.equal(stopped.streaming, false)
  assert.equal(stopped.messages.at(-1).status, 'stopped')
  assert.equal(stopped.streamGeneration, streaming.streamGeneration + 1)

  const retried = reduceChatState(stopped, {
    type: 'start-retry',
    messageId: 8,
    message: { id: 'retry-pending', role: 'assistant', content: '', status: 'streaming' },
  })
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
  assert.match(api, /TextDecoder\([^)]*\)/)
  assert.match(api, /stream:\s*true/)
  assert.match(api, /Accept:\s*['"]text\/event-stream['"]/)
  assert.match(api, /['"]Content-Type['"]:\s*['"]application\/json['"]/)
  assert.match(api, /contentType\.toLowerCase\(\)\.includes\(['"]text\/event-stream['"]\)/)
  assert.match(api, /response\.json\(\)/)
  assert.match(api, /getAccessToken\(\)/)
  assert.match(api, /clearAuthState\(\)/)
  assert.doesNotMatch(api, /catch\s*\([^)]*\)\s*\{[^}]*AbortError/s)
  assert.doesNotMatch(api, /axios\.create|createApiClient/)
})
