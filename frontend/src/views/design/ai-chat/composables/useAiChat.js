import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import {
  createSession,
  deleteAttachment,
  getConfig,
  getSession,
  listSessions,
  streamRetry,
  streamTurn,
  uploadAttachment,
} from '@/api/aiChat'
import { requestId, modeCanSubmit } from '../state'
import { useChatModes } from './useChatModes'
import { useChatDrafts } from './useChatDrafts'
import { msgError } from '@/utils/feedback'

function dataOf(response) {
  return response?.data ?? response
}

function errorMessage(error) {
  const detail = error?.detail || error?.response?.data?.detail
  if (error?.status === 409 || error?.response?.status === 409) {
    return typeof detail === 'string' ? detail : '会话状态已变化，请先刷新，再决定是否重试。'
  }
  if (typeof detail === 'string' && detail) return detail
  if (detail?.message) return detail.message
  return error?.message || '请求失败，请重试'
}

function attachFiles(messages, attachments) {
  return messages.map(message => ({
    ...message,
    attachments: attachments.filter(item => item.message_id === message.id),
  }))
}

export function useAiChat() {
  const auth = useAuthStore()
  const config = ref({ configured: true, message: '' })
  const sessions = ref([])
  const currentSessionId = ref(null)
  const messages = ref([])
  const draftAttachments = ref([])
  const prompt = ref('')
  const drawerOpen = ref(false)
  const initializing = ref(true)
  const sessionLoading = ref(false)
  const streaming = ref(false)
  const preparing = ref(false)
  const busy = computed(() => streaming.value || preparing.value)
  const error = ref(null)
  const modes = useChatModes({ messages, streaming: busy, currentSessionId })
  const drafts = useChatDrafts({ prompt, attachments: draftAttachments, modes, sessionId: currentSessionId })
  const activeKey = `ai-chat-session:${auth.user?.id}`

  let workspaceGeneration = 0
  let streamGeneration = 0
  let localSequence = 0
  let sessionPromise = null
  let abortController = null
  let streamAssistantId = null

  const canWrite = computed(() => auth.hasPermission('ai_chat:write'))
  const uploadsPending = computed(() => draftAttachments.value.some(item => item.optimistic))
  const canSubmit = computed(() => canWrite.value
    && !busy.value
    && !sessionLoading.value
    && !uploadsPending.value
    && modeCanSubmit({ mode: modes.selected.value, prompt: prompt.value, attachments: draftAttachments.value,
      loading: modes.loading.value, error: modes.error.value, locked: modes.locked.value }))
  const currentSession = computed(() => (
    sessions.value.find(item => item.id === currentSessionId.value) || null
  ))

  function nextLocalId(prefix) {
    localSequence += 1
    return `${prefix}-${Date.now()}-${localSequence}`
  }

  function abortActive() {
    streamGeneration += 1
    abortController?.abort()
    abortController = null
    streaming.value = false
    streamAssistantId = null
  }

  async function loadSessions() {
    const response = dataOf(await listSessions({ limit: 30 })) || {}
    sessions.value = response.items || []
  }

  async function loadDetail(
    sessionId,
    expectedWorkspace = workspaceGeneration,
    expectedStream = null,
    preserveDrafts = false,
  ) {
    sessionLoading.value = true
    try {
      const detail = dataOf(await getSession(sessionId)) || {}
      if (expectedWorkspace !== workspaceGeneration || currentSessionId.value !== sessionId
          || (expectedStream != null && expectedStream !== streamGeneration)) return
      const attachments = detail.attachments || []
      messages.value = attachFiles(detail.messages || [], attachments)
      if (!preserveDrafts) {
        draftAttachments.value = attachments.filter(item => item.message_id == null)
      }
      const session = detail.session
      if (session) {
        if (!preserveDrafts || messages.value.length) modes.restore(session.mode)
        const index = sessions.value.findIndex(item => item.id === session.id)
        if (index === -1) sessions.value.unshift(session)
        else sessions.value.splice(index, 1, session)
      }
    } finally {
      if (expectedWorkspace === workspaceGeneration && currentSessionId.value === sessionId) {
        sessionLoading.value = false
      }
    }
  }

  async function ensureSession() {
    if (currentSessionId.value) return currentSessionId.value
    if (sessionPromise) return sessionPromise
    const expectedWorkspace = workspaceGeneration
    sessionPromise = createSession({}).then(response => {
      const session = dataOf(response)
      if (expectedWorkspace !== workspaceGeneration) throw new Error('会话已切换，请重试')
      currentSessionId.value = session.id
      drafts.materialize(session.id)
      sessionStorage.setItem(activeKey, String(session.id))
      sessions.value = [session, ...sessions.value.filter(item => item.id !== session.id)]
      return session.id
    }).finally(() => { sessionPromise = null })
    return sessionPromise
  }

  async function uploadDraft(file) {
    if (!canWrite.value) throw new Error('你没有发送权限')
    if (draftAttachments.value.length >= 5) throw new Error('最多上传 5 个附件')
    const localId = nextLocalId('upload')
    const optimistic = {
      id: localId,
      original_name: file.name,
      file_size: file.size,
      optimistic: true,
    }
    draftAttachments.value.push(optimistic)
    try {
      const sessionId = await ensureSession()
      const uploaded = dataOf(await uploadAttachment(sessionId, file))
      const index = draftAttachments.value.findIndex(item => item.id === localId)
      if (index !== -1) draftAttachments.value.splice(index, 1, uploaded)
      return uploaded
    } catch (uploadError) {
      draftAttachments.value = draftAttachments.value.filter(item => item.id !== localId)
      throw uploadError
    }
  }

  async function removeDraft(attachmentId) {
    const index = draftAttachments.value.findIndex(item => item.id === attachmentId)
    if (index === -1) return
    const [removed] = draftAttachments.value.splice(index, 1)
    if (removed.optimistic) return
    try {
      await deleteAttachment(attachmentId)
    } catch (deleteError) {
      draftAttachments.value.splice(index, 0, removed)
      throw deleteError
    }
  }

  function applyMeta(data, pendingTurn) {
    const userMaterialized = !pendingTurn.userMessage || Boolean(data.user_message_id)
    if (data.user_message_id && pendingTurn.userMessage
        && !messages.value.some(message => message.id === data.user_message_id)) {
      messages.value.push({
        ...pendingTurn.userMessage,
        id: data.user_message_id,
        session_id: data.session_id,
      })
    }
    if (!data.assistant_message_id) return false
    streamAssistantId = data.assistant_message_id
    if (!messages.value.some(message => message.id === data.assistant_message_id)) {
      messages.value.push({
        ...pendingTurn.assistantMessage,
        id: data.assistant_message_id,
        session_id: data.session_id,
        status: data.status || 'streaming',
      })
    }
    return userMaterialized
  }

  function acknowledgeDraft(pendingTurn) {
    const snapshot = pendingTurn.composerSnapshot
    if (!snapshot || pendingTurn.acknowledged) return
    pendingTurn.acknowledged = true
    if (prompt.value === snapshot.prompt) prompt.value = ''
    const acknowledgedIds = new Set(snapshot.attachmentIds)
    draftAttachments.value = draftAttachments.value.filter(item => !acknowledgedIds.has(item.id))
  }

  function updateAssistant(messageId, changes) {
    messages.value = messages.value.map(message => (
      message.id === messageId ? { ...message, ...changes } : message
    ))
  }

  function handleFrame(frame, generation, pendingTurn, sessionId, expectedWorkspace) {
    if (generation !== streamGeneration || expectedWorkspace !== workspaceGeneration
        || currentSessionId.value !== sessionId) return
    const data = frame.data || {}
    if (frame.event === 'heartbeat') return
    if (frame.event === 'meta') {
      if (data.session_id != null && data.session_id !== sessionId) return
      if (applyMeta(data, pendingTurn)) acknowledgeDraft(pendingTurn)
      return
    }
    const targetId = streamAssistantId
    if (frame.event === 'delta') {
      if (targetId == null) return
      const current = messages.value.find(message => message.id === targetId)
      updateAssistant(targetId, { content: `${current?.content || ''}${data.text || ''}` })
    } else if (frame.event === 'done') {
      updateAssistant(targetId, { status: data.status || 'completed', error_message: null })
      streaming.value = false
    } else if (frame.event === 'error') {
      const message = data.message || '生成失败，请重试'
      updateAssistant(targetId, { status: 'failed', error_message: message })
      error.value = { message }
      streaming.value = false
    }
  }

  async function refreshAfterStream(sessionId, generation, expectedWorkspace) {
    try {
      await Promise.all([loadDetail(sessionId, expectedWorkspace, generation, true), loadSessions()])
    } catch {
      if (!error.value) {
        error.value = { message: '回答已结束，但会话刷新失败，请手动刷新。' }
      }
    }
  }

  async function reloadFailedSession(sessionId, generation, expectedWorkspace) {
    if (generation !== streamGeneration
        || expectedWorkspace !== workspaceGeneration
        || currentSessionId.value !== sessionId) return
    try {
      await loadDetail(sessionId, expectedWorkspace, generation, true)
    } catch {
      // Keep the actionable stream error; the explicit refresh action remains available.
    }
  }

  async function runStream({ retryMessageId = null } = {}) {
    if (!canWrite.value || busy.value) return
    const composerPrompt = prompt.value
    const mode = modes.selected.value
    const content = composerPrompt.trim() || (!modes.locked.value ? mode?.start_text || '' : '')
    const outgoing = [...draftAttachments.value]
    if (!retryMessageId && !content && outgoing.length === 0) return
    const beforePrepare = workspaceGeneration
    preparing.value = true
    let sessionId
    try { sessionId = retryMessageId ? currentSessionId.value : await ensureSession() }
    finally { preparing.value = false }
    if (beforePrepare !== workspaceGeneration) return
    if (!sessionId) return

    const generation = ++streamGeneration
    const expectedWorkspace = workspaceGeneration
    const pendingTurn = {
      userMessage: retryMessageId ? null : {
        role: 'user',
        content,
        status: 'completed',
        attachments: outgoing,
      },
      assistantMessage: {
        role: 'assistant',
        content: '',
        status: 'streaming',
        retry_of_message_id: retryMessageId,
      },
      composerSnapshot: retryMessageId ? null : {
        prompt: composerPrompt,
        attachmentIds: outgoing.map(item => item.id),
      },
      acknowledged: false,
    }
    streamAssistantId = null
    streaming.value = true
    error.value = null
    abortController = new AbortController()

    try {
      const options = {
        signal: abortController.signal,
        onEvent: frame => handleFrame(
          frame,
          generation,
          pendingTurn,
          sessionId,
          expectedWorkspace,
        ),
      }
      if (retryMessageId) {
        await streamRetry(retryMessageId, { request_id: requestId() }, options)
      } else {
        await streamTurn(sessionId, {
          request_id: requestId(),
          content,
          attachment_ids: outgoing.map(item => item.id),
          mode_id: mode?.id || null,
          mode_version: mode?.version || null,
        }, options)
      }
      if (generation !== streamGeneration || expectedWorkspace !== workspaceGeneration) return
      streaming.value = false
      await refreshAfterStream(sessionId, generation, expectedWorkspace)
    } catch (streamError) {
      if (streamError?.name === 'AbortError' || generation !== streamGeneration
          || expectedWorkspace !== workspaceGeneration
          || currentSessionId.value !== sessionId) return
      const message = errorMessage(streamError)
      if (streamAssistantId != null) {
        updateAssistant(streamAssistantId, { status: 'failed', error_message: message })
      }
      error.value = { message, conflict: streamError?.status === 409 || streamError?.response?.status === 409 }
      streaming.value = false
      await reloadFailedSession(sessionId, generation, expectedWorkspace)
      if (generation === streamGeneration && !messages.value.length && mode
          && [409, 503].includes(streamError?.status || streamError?.response?.status)) modes.error.value = message
    } finally {
      if (generation === streamGeneration) {
        abortController = null
        streamAssistantId = null
      }
    }
  }

  async function send() {
    if (!canSubmit.value) return
    try {
      await runStream()
    } catch (sendError) {
      msgError(errorMessage(sendError))
    }
  }

  async function retry(messageId) {
    if (!canWrite.value || streaming.value) return
    await runStream({ retryMessageId: messageId })
  }

  async function stop() {
    if (!streaming.value) return
    const sessionId = currentSessionId.value
    const expectedWorkspace = workspaceGeneration
    const targetId = streamAssistantId
    streamGeneration += 1
    const stoppedGeneration = streamGeneration
    abortController?.abort()
    abortController = null
    streaming.value = false
    if (targetId) updateAssistant(targetId, { status: 'stopped' })
    streamAssistantId = null
    if (sessionId) {
      await new Promise(resolve => setTimeout(resolve, 150))
      if (currentSessionId.value === sessionId) {
        await loadDetail(sessionId, expectedWorkspace, stoppedGeneration, true)
      }
    }
  }

  function newConversation() {
    if (!sessionLoading.value) drafts.save()
    abortActive()
    workspaceGeneration += 1
    currentSessionId.value = null
    sessionLoading.value = false
    messages.value = []
    draftAttachments.value = []
    prompt.value = ''
    error.value = null
    drawerOpen.value = false
    modes.restore()
    sessionStorage.removeItem(activeKey)
    drafts.restore()
  }

  async function selectSession(sessionId) {
    if (sessionId === currentSessionId.value) {
      drawerOpen.value = false
      return
    }
    if (!sessionLoading.value) drafts.save()
    abortActive()
    workspaceGeneration += 1
    currentSessionId.value = sessionId
    messages.value = []
    draftAttachments.value = []
    prompt.value = ''
    error.value = null
    drawerOpen.value = false
    modes.restore()
    sessionStorage.setItem(activeKey, String(sessionId))
    const expectedWorkspace = workspaceGeneration
    await loadDetail(sessionId)
    if (expectedWorkspace !== workspaceGeneration || currentSessionId.value !== sessionId) return
    drafts.restore({ locked: modes.locked.value })
  }

  async function refreshCurrent() {
    if (!currentSessionId.value) return
    error.value = null
    await loadDetail(currentSessionId.value, workspaceGeneration, null, true)
  }

  async function initialize() {
    initializing.value = true
    try {
      const [configResponse] = await Promise.all([getConfig(), loadSessions()])
      config.value = dataOf(configResponse) || config.value
      const savedId = Number(sessionStorage.getItem(activeKey))
      if (savedId && sessions.value.some(session => session.id === savedId)) await selectSession(savedId)
    } catch (initError) {
      error.value = { message: errorMessage(initError) }
    } finally {
      initializing.value = false
    }
  }

  onMounted(initialize)
  onBeforeUnmount(() => {
    workspaceGeneration += 1
    abortActive()
  })

  return {
    config,
    sessions,
    currentSessionId,
    currentSession,
    messages,
    draftAttachments,
    prompt,
    drawerOpen,
    initializing,
    sessionLoading,
    streaming,
    busy,
    modes,
    error,
    canWrite,
    canSubmit,
    uploadDraft,
    removeDraft,
    send,
    stop,
    retry,
    newConversation,
    selectSession,
    refreshCurrent,
  }
}
