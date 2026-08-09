export const STARTERS = Object.freeze([
  Object.freeze({
    id: 'customer-needs',
    title: '客户需求分析',
    prompt: '请分析以下客户需求，按已知信息、关键目标、待确认问题、风险和下一步行动整理，并指出优先级。',
  }),
  Object.freeze({
    id: 'product-solution',
    title: '产品方案',
    prompt: '请根据以下客户需求制定产品方案，说明产品组合、选型理由、交付建议、风险和需要客户确认的事项。',
  }),
  Object.freeze({
    id: 'marketing-copy',
    title: '营销推广方案',
    prompt: '请基于以下产品与客户信息制定营销推广方案，包含目标受众、核心卖点、渠道内容、执行节奏和效果衡量。',
  }),
  Object.freeze({
    id: 'customer-communication',
    title: '邮件与沟通话术',
    prompt: '请根据以下背景起草专业、自然的客户邮件与沟通话术，给出主题、正文、跟进问题和下一步行动。',
  }),
])

const DEFAULT_STATE = Object.freeze({
  sessions: [],
  activeSessionId: null,
  messages: [],
  prompt: '',
  draftAttachments: [],
  streaming: false,
  streamGeneration: 0,
  streamMessageId: null,
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

function applyStreamEvent(state, action) {
  if (action.generation !== state.streamGeneration) return state

  const frame = action.event || {}
  const data = frame.data || {}
  if (frame.event === 'heartbeat') {
    return { ...state, lastHeartbeat: data }
  }
  if (frame.event === 'meta') {
    const previousId = state.streamMessageId
    const nextId = data.assistant_message_id ?? previousId
    const messages = updateStreamMessage(state, message => ({
      ...message,
      id: nextId ?? message.id,
      session_id: data.session_id ?? message.session_id,
      status: data.status || 'streaming',
    }))
    return { ...state, messages, streamMessageId: nextId }
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
    }
  }
  return state
}

export function reduceChatState(state, action) {
  switch (action.type) {
    case 'apply-starter':
      return { ...state, prompt: action.starter?.prompt || '' }
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
      const message = action.message || {
        id: `stream-${generation}`,
        role: 'assistant',
        content: '',
        status: 'streaming',
      }
      return {
        ...state,
        messages: [...state.messages, message],
        streaming: true,
        streamGeneration: generation,
        streamMessageId: message.id,
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
        messages: [...state.messages, message],
        streaming: true,
        streamGeneration: generation,
        streamMessageId: message.id,
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
