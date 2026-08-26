export function modeCanSubmit({ mode = null, prompt = '', attachments = [], loading = false, error = '', locked = false } = {}) {
  if (loading || error || (mode && !mode.version)) return false
  if (prompt.trim()) return true
  if (mode && !locked) return Boolean(mode.start_text)
  return attachments.length > 0
}

const DEFAULT_STATE = Object.freeze({
  sessions: [],
  activeSessionId: null,
  messages: [],
  prompt: '',
  draftAttachments: [],
  streaming: false,
  streamGeneration: 0,
  streamMessageId: null,
  pendingTurn: null,
  error: null,
  lastHeartbeat: null,
  streamSummary: null,
})

let requestSequence = 0

export function requestId() {
  requestSequence = (requestSequence + 1) % 1679616
  return `chat_${Date.now().toString(36)}_${requestSequence.toString(36)}_${Math.random().toString(36).slice(2, 10)}`
}

export function isComposerSubmit(event) {
  return event?.key === 'Enter'
    && !event.isComposing
    && event.keyCode !== 229
    && !event.shiftKey
}

export function createInitialState(overrides = {}) {
  return {
    ...DEFAULT_STATE,
    ...overrides,
    sessions: [...(overrides.sessions || DEFAULT_STATE.sessions)],
    messages: [...(overrides.messages || DEFAULT_STATE.messages)],
    draftAttachments: [...(overrides.draftAttachments || DEFAULT_STATE.draftAttachments)],
  }
}

function updateStreamMessage(state, update) {
  const targetId = state.streamMessageId
  if (targetId == null) return state.messages
  let found = false
  const messages = state.messages.map(message => {
    if (message.id !== targetId) return message
    found = true
    return update(message)
  })
  if (!found) {
    messages.push(update({
      id: targetId || `stream-${state.streamGeneration}`,
      role: 'assistant',
      content: '',
      status: 'streaming',
    }))
  }
  return messages
}

function materializePendingMessages(state, data) {
  const messages = [...state.messages]
  const pending = state.pendingTurn || {}
  if (data.user_message_id && pending.userMessage
      && !messages.some(message => message.id === data.user_message_id)) {
    messages.push({
      ...pending.userMessage,
      id: data.user_message_id,
      session_id: data.session_id ?? pending.userMessage.session_id,
    })
  }
  if (data.assistant_message_id) {
    const index = messages.findIndex(message => message.id === data.assistant_message_id)
    if (index === -1) {
      messages.push({
        ...(pending.assistantMessage || { role: 'assistant', content: '' }),
        id: data.assistant_message_id,
        session_id: data.session_id,
        status: data.status || 'streaming',
      })
    } else {
      messages[index] = { ...messages[index], status: data.status || messages[index].status }
    }
  }
  return messages
}

function acknowledgedComposer(state, data) {
  const pending = state.pendingTurn
  const acknowledged = Boolean(data.assistant_message_id)
    && (!pending?.userMessage || Boolean(data.user_message_id))
  const snapshot = pending?.composerSnapshot
  if (!acknowledged || !snapshot) {
    return {
      prompt: state.prompt,
      draftAttachments: state.draftAttachments,
      pendingTurn: acknowledged ? null : pending,
    }
  }
  const acknowledgedIds = new Set(snapshot.attachmentIds)
  return {
    prompt: state.prompt === snapshot.prompt ? '' : state.prompt,
    draftAttachments: state.draftAttachments.filter(item => !acknowledgedIds.has(item.id)),
    pendingTurn: null,
  }
}

function applyStreamEvent(state, action) {
  if (action.generation !== state.streamGeneration) return state

  const frame = action.event || {}
  const data = frame.data || {}
  if (frame.event === 'heartbeat') {
    return { ...state, lastHeartbeat: data }
  }
  if (frame.event === 'meta') {
    const nextId = data.assistant_message_id ?? state.streamMessageId
    const composer = acknowledgedComposer(state, data)
    return {
      ...state,
      messages: materializePendingMessages(state, data),
      streamMessageId: nextId,
      ...composer,
    }
  }
  if (frame.event === 'delta') {
    const text = typeof data.text === 'string' ? data.text : ''
    return {
      ...state,
      messages: updateStreamMessage(state, message => ({
        ...message,
        content: `${message.content || ''}${text}`,
        status: 'streaming',
      })),
    }
  }
  if (frame.event === 'done') {
    return {
      ...state,
      streaming: false,
      messages: updateStreamMessage(state, message => ({
        ...message,
        status: data.status || 'completed',
        error_message: null,
      })),
      streamSummary: data,
      error: null,
      pendingTurn: null,
    }
  }
  if (frame.event === 'error') {
    const error = {
      code: data.code || 'stream_error',
      message: data.message || '生成失败，请重试',
    }
    return {
      ...state,
      streaming: false,
      messages: updateStreamMessage(state, message => ({
        ...message,
        status: 'failed',
        error_message: error.message,
      })),
      error,
      pendingTurn: null,
    }
  }
  return state
}

export function reduceChatState(state, action) {
  switch (action.type) {
    case 'set-prompt':
      return { ...state, prompt: action.prompt || '' }
    case 'set-sessions':
      return { ...state, sessions: [...(action.sessions || [])] }
    case 'set-messages':
      return { ...state, messages: [...(action.messages || [])] }
    case 'add-draft-attachment': {
      if (!action.attachment || state.draftAttachments.length >= 5) return state
      if (state.draftAttachments.some(item => item.id === action.attachment.id)) return state
      return { ...state, draftAttachments: [...state.draftAttachments, action.attachment] }
    }
    case 'remove-draft-attachment':
      return {
        ...state,
        draftAttachments: state.draftAttachments.filter(item => item.id !== action.attachmentId),
      }
    case 'start-stream': {
      const generation = state.streamGeneration + 1
      return {
        ...state,
        streaming: true,
        streamGeneration: generation,
        streamMessageId: null,
        pendingTurn: action.pending || {
          userMessage: null,
          assistantMessage: action.message || { role: 'assistant', content: '', status: 'streaming' },
        },
        error: null,
        lastHeartbeat: null,
        streamSummary: null,
      }
    }
    case 'start-retry': {
      const generation = state.streamGeneration + 1
      const message = {
        ...(action.message || {
          id: `retry-${generation}`,
          role: 'assistant',
          content: '',
          status: 'streaming',
        }),
        retry_of_message_id: action.messageId,
      }
      return {
        ...state,
        streaming: true,
        streamGeneration: generation,
        streamMessageId: null,
        pendingTurn: {
          userMessage: null,
          assistantMessage: message,
        },
        error: null,
        lastHeartbeat: null,
        streamSummary: null,
      }
    }
    case 'stream-event':
      return applyStreamEvent(state, action)
    case 'stop-stream':
      return {
        ...state,
        streaming: false,
        streamGeneration: state.streamGeneration + 1,
        messages: state.streaming
          ? updateStreamMessage(state, message => ({ ...message, status: 'stopped' }))
          : state.messages,
        pendingTurn: null,
      }
    case 'switch-session':
      return createInitialState({
        sessions: state.sessions,
        activeSessionId: action.sessionId ?? null,
        messages: action.messages || [],
        streamGeneration: state.streamGeneration + 1,
      })
    default:
      return state
  }
}

function invalidDataEvent() {
  return {
    event: 'error',
    data: {
      code: 'invalid_sse_data',
      message: '模型返回了无法解析的消息',
    },
  }
}

function parseFrame(frame) {
  let event = 'message'
  const dataLines = []
  for (const line of frame.replace(/\r\n?/g, '\n').split('\n')) {
    if (!line || line.startsWith(':')) continue
    const colon = line.indexOf(':')
    const field = colon === -1 ? line : line.slice(0, colon)
    let value = colon === -1 ? '' : line.slice(colon + 1)
    if (value.startsWith(' ')) value = value.slice(1)
    if (field === 'event') event = value || 'message'
    if (field === 'data') dataLines.push(value)
  }
  if (dataLines.length === 0) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return invalidDataEvent()
  }
}

export function createSseParser() {
  let buffer = ''

  function drain(allowPartial = false) {
    const events = []
    while (buffer) {
      const match = /\r\n\r\n|\n\n|\r\r/.exec(buffer)
      if (!match && !allowPartial) break
      const frame = match ? buffer.slice(0, match.index) : buffer
      buffer = match ? buffer.slice(match.index + match[0].length) : ''
      const parsed = parseFrame(frame)
      if (parsed) events.push(parsed)
      if (!match) break
    }
    return events
  }

  return {
    push(chunk) {
      buffer += chunk || ''
      return drain(false)
    },
    flush() {
      return drain(true)
    },
  }
}

export async function consumeSseStream(body, { onEvent } = {}) {
  const parser = createSseParser()
  const decoder = new TextDecoder('utf-8')
  const reader = body.getReader()
  let terminal = false

  const dispatch = async frames => {
    for (const frame of frames) {
      if (frame.event === 'done' || frame.event === 'error') terminal = true
      if (onEvent) await onEvent(frame)
    }
  }

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      await dispatch(parser.push(decoder.decode(value, { stream: true })))
    }
    await dispatch(parser.push(decoder.decode()))
    await dispatch(parser.flush())
  } finally {
    reader.releaseLock()
  }

  if (!terminal) {
    throw new Error('模型连接意外中断，请重试')
  }
}
