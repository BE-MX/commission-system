import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  createSession, createTurn, deleteAsset, getActiveJob, getConfig, getSession,
  listSessions, retryJob, uploadAsset,
} from '@/api/designImage'
import { msgError } from '@/utils/feedback'
import {
  acceptConversationResponse, advanceJob, canStartSend, replaceActiveJob,
  restoreActiveJob, upsertAttachment,
} from '../state'
import { useAssetObjectUrls } from './useAssetObjectUrls'
import { useJobPolling } from './useJobPolling'

const ACTIVE_STATUSES = new Set(['queued', 'running'])

function requestId(prefix) {
  const uuid = globalThis.crypto?.randomUUID?.()
  return `${prefix}-${uuid || `${Date.now()}-${Math.random().toString(36).slice(2)}`}`
}

function safeRequestMessage(error) {
  const status = error?.response?.status
  if (status === 429) return '今日额度已用完或当前任务较多，请稍后再试'
  if (status === 409) return '已有任务正在生成，请等待完成后再发送'
  if (status === 413) return '图片超过上传限制，请压缩后重试'
  if (status === 400 || status === 422) return '图片或输入内容不符合要求，请调整后重试'
  return '操作未完成，请检查网络后重试'
}

export function useImageStudio() {
  const sessions = ref([])
  const nextCursor = ref(null)
  const currentSessionId = ref(null)
  const currentSession = ref(null)
  const messages = ref([])
  const assets = ref([])
  const jobs = ref([])
  const config = ref({ sizes: [], qualities: [], remaining_today: 0, daily_limit: 0 })
  const prompt = ref('')
  const size = ref('1024x1024')
  const quality = ref('medium')
  const draftAttachments = ref([])
  const baseAsset = ref(null)
  const sendInFlight = ref(false)
  const uploadInFlight = ref(0)
  const initializing = ref(true)
  const sessionsLoading = ref(false)
  const drawerOpen = ref(false)
  const lightboxAsset = ref(null)
  const lightboxUrl = ref(null)
  const activeJobs = reactive(new Map())
  const jobSnapshots = new Map()
  const assetUrls = useAssetObjectUrls()
  const polling = useJobPolling()
  let conversationGeneration = 0
  let sessionCreationPromise = null

  const activeJob = computed(() => [...activeJobs.values()].find(job => ACTIVE_STATUSES.has(job.status)) ?? null)
  const canSend = computed(() => canStartSend({
    sendInFlight: sendInFlight.value,
    uploadInFlight: uploadInFlight.value > 0,
    activeJob: activeJob.value,
  }) && prompt.value.trim().length > 0 && config.value.remaining_today > 0)

  function mergeSession(session) {
    if (!session) return
    const index = sessions.value.findIndex(item => item.id === session.id)
    sessions.value = index === -1
      ? [session, ...sessions.value]
      : sessions.value.map(item => item.id === session.id ? { ...item, ...session } : item)
  }

  function mergeSessionPage(items, append) {
    const incomingIds = new Set(items.map(item => item.id))
    const existingById = new Map(sessions.value.map(item => [item.id, item]))
    const incoming = items.map(item => ({ ...existingById.get(item.id), ...item }))
    if (append) {
      const additions = incoming.filter(item => !existingById.has(item.id))
      sessions.value = [
        ...sessions.value.map(item => incomingIds.has(item.id)
          ? incoming.find(candidate => candidate.id === item.id)
          : item),
        ...additions,
      ]
      return
    }
    const locallyCreated = sessions.value.filter(item => !incomingIds.has(item.id))
    sessions.value = [...locallyCreated, ...incoming]
  }

  function mergeJob(job) {
    const merged = advanceJob(jobSnapshots.get(job.id), job)
    jobSnapshots.set(merged.id, merged)
    if (ACTIVE_STATUSES.has(merged.status)) activeJobs.set(merged.id, merged)
    else activeJobs.delete(merged.id)
    if (currentSessionId.value === merged.session_id) {
      const next = replaceActiveJob({ activeJobId: activeJob.value?.id ?? null, jobs: jobs.value }, merged)
      jobs.value = next.jobs
    }
    return merged
  }

  async function hydrateThumbnails(rows, token) {
    await Promise.allSettled(rows
      .filter(asset => asset.asset_type !== 'thumbnail')
      .map(asset => assetUrls.load(asset.id, { thumbnail: true, token })))
  }

  function startActivePolling(job) {
    if (!job || !ACTIVE_STATUSES.has(job.status)) return
    polling.startPolling({
      sessionId: job.session_id,
      jobId: job.id,
      onUpdate: async incoming => {
        const merged = mergeJob(incoming)
        if (!ACTIVE_STATUSES.has(merged.status)) {
          await loadConfig()
          if (currentSessionId.value === merged.session_id) await selectSession(merged.session_id)
        }
        return merged
      },
    })
  }

  async function loadConfig() {
    const response = await getConfig()
    config.value = response?.data ?? config.value
    size.value = size.value || config.value.default_size
    quality.value = quality.value || config.value.default_quality
  }

  async function loadSessions({ append = false, requestGeneration = conversationGeneration } = {}) {
    if (sessionsLoading.value) return
    sessionsLoading.value = true
    try {
      const response = await listSessions(append && nextCursor.value ? { cursor: nextCursor.value } : {})
      const page = response?.data ?? { items: [], next_cursor: null }
      const requestIsCurrent = acceptConversationResponse(requestGeneration, conversationGeneration)
      mergeSessionPage(page.items || [], append)
      if (append || requestIsCurrent) nextCursor.value = page.next_cursor ?? null
    } catch (error) {
      msgError(safeRequestMessage(error))
    } finally {
      sessionsLoading.value = false
    }
  }

  async function selectSession(sessionId) {
    conversationGeneration += 1
    const responseGeneration = conversationGeneration
    polling.stopPolling()
    const token = assetUrls.beginBatch()
    currentSessionId.value = sessionId
    currentSession.value = null
    messages.value = []
    assets.value = []
    jobs.value = []
    draftAttachments.value = []
    baseAsset.value = null
    lightboxAsset.value = null
    lightboxUrl.value = null
    drawerOpen.value = false
    try {
      const response = await getSession(sessionId)
      if (responseGeneration !== conversationGeneration || currentSessionId.value !== sessionId) return
      const detail = response?.data ?? {}
      currentSession.value = detail.session ?? null
      messages.value = detail.messages ?? []
      assets.value = detail.assets ?? []
      jobs.value = (detail.jobs ?? []).map(job => {
        const merged = advanceJob(jobSnapshots.get(job.id), job)
        jobSnapshots.set(merged.id, merged)
        if (ACTIVE_STATUSES.has(merged.status)) activeJobs.set(merged.id, merged)
        else activeJobs.delete(merged.id)
        return merged
      })
      draftAttachments.value = assets.value
        .filter(asset => asset.asset_type === 'upload' && asset.status === 'draft')
        .map(asset => ({
          uploadId: `draft-${asset.id}`,
          name: `参考图 ${asset.id}`,
          status: 'ready',
          asset,
        }))
      mergeSession(detail.session)
      const tracked = activeJob.value
      if (tracked) startActivePolling(tracked)
      void hydrateThumbnails(assets.value, token).catch(() => {})
    } catch (error) {
      if (responseGeneration === conversationGeneration) msgError(safeRequestMessage(error))
    }
  }

  async function newConversation() {
    conversationGeneration += 1
    const responseGeneration = conversationGeneration
    polling.stopPolling()
    assetUrls.beginBatch()
    currentSessionId.value = null
    currentSession.value = null
    messages.value = []
    assets.value = []
    jobs.value = []
    draftAttachments.value = []
    baseAsset.value = null
    drawerOpen.value = false
    try {
      const response = await createSession({ title: '新对话' })
      const session = response?.data
      mergeSession(session)
      if (responseGeneration === conversationGeneration) await selectSession(session.id)
      return session
    } catch (error) {
      msgError(safeRequestMessage(error))
      return null
    }
  }

  async function ensureSession() {
    if (currentSessionId.value) return currentSession.value
    if (!sessionCreationPromise) {
      sessionCreationPromise = newConversation().finally(() => { sessionCreationPromise = null })
    }
    return sessionCreationPromise
  }

  async function uploadReference(file, onProgress) {
    if (sendInFlight.value || draftAttachments.value.length + uploadInFlight.value >= 4) {
      msgError('每轮最多添加 4 张参考图')
      throw new Error('upload guarded')
    }
    const uploadId = requestId('upload')
    uploadInFlight.value += 1
    let uploadGeneration = null
    let sessionIdSnapshot = null
    try {
      const session = await ensureSession()
      if (!session) throw new Error('session unavailable')
      if (currentSessionId.value !== session.id || draftAttachments.value.length >= 4) {
        throw new Error('upload context changed')
      }
      uploadGeneration = conversationGeneration
      sessionIdSnapshot = session.id
      draftAttachments.value = upsertAttachment(draftAttachments.value, uploadId, {
        name: file.name, status: 'uploading', progress: 0,
      })
      const response = await uploadAsset(session.id, file)
      const asset = response?.data
      if (uploadGeneration !== conversationGeneration || currentSessionId.value !== sessionIdSnapshot) return asset
      draftAttachments.value = upsertAttachment(draftAttachments.value, uploadId, {
        name: file.name, status: 'ready', asset,
      })
      await assetUrls.load(asset.id, { thumbnail: true })
      onProgress?.(100)
      return asset
    } catch (error) {
      draftAttachments.value = draftAttachments.value.filter(item => item.uploadId !== uploadId)
      if (error?.message !== 'upload context changed' && (uploadGeneration === null || (
        uploadGeneration === conversationGeneration && currentSessionId.value === sessionIdSnapshot
      ))) msgError(safeRequestMessage(error))
      throw error
    } finally {
      uploadInFlight.value -= 1
    }
  }

  async function removeAttachment(item) {
    if (item.status === 'ready') {
      try {
        await deleteAsset(item.asset.id)
      } catch (error) {
        msgError(safeRequestMessage(error))
        return
      }
    }
    draftAttachments.value = draftAttachments.value.filter(candidate => candidate.uploadId !== item.uploadId)
  }

  async function submit() {
    if (!canSend.value) return
    sendInFlight.value = true
    let responseGeneration = null
    let sessionIdSnapshot = null
    try {
      const session = await ensureSession()
      if (!session) return
      responseGeneration = conversationGeneration
      sessionIdSnapshot = session.id
      const body = {
        request_id: requestId('turn'),
        prompt: prompt.value.trim(),
        base_asset_id: baseAsset.value?.id ?? null,
        reference_asset_ids: draftAttachments.value.filter(item => item.status === 'ready').map(item => item.asset.id),
        size: size.value,
        quality: quality.value,
      }
      const response = await createTurn(session.id, body)
      const result = response?.data
      mergeJob(result.job)
      mergeSession(result.session)
      if (responseGeneration === conversationGeneration && currentSessionId.value === sessionIdSnapshot) {
        messages.value = [...messages.value, result.message]
        prompt.value = ''
        draftAttachments.value = []
        baseAsset.value = null
      }
      startActivePolling(result.job)
    } catch (error) {
      if (responseGeneration === null || (
        responseGeneration === conversationGeneration && currentSessionId.value === sessionIdSnapshot
      )) msgError(safeRequestMessage(error))
    } finally {
      sendInFlight.value = false
    }
  }

  async function retry(job) {
    if (activeJob.value || sendInFlight.value) return
    sendInFlight.value = true
    try {
      const response = await retryJob(job.id, { request_id: requestId('retry') })
      const result = response?.data
      mergeJob(result.job)
      startActivePolling(result.job)
    } catch (error) {
      msgError(safeRequestMessage(error))
    } finally {
      sendInFlight.value = false
    }
  }

  function chooseBaseAsset(asset) {
    baseAsset.value = asset
  }

  async function openLightbox(asset) {
    lightboxAsset.value = asset
    lightboxUrl.value = null
    try {
      const url = await assetUrls.load(asset.id, { thumbnail: false })
      if (lightboxAsset.value?.id === asset.id) lightboxUrl.value = url
    } catch {
      if (lightboxAsset.value?.id === asset.id) closeLightbox()
      msgError('无法读取原图，请稍后重试')
    }
  }

  function closeLightbox() {
    lightboxAsset.value = null
    lightboxUrl.value = null
  }

  async function downloadAsset(asset) {
    try {
      const url = await assetUrls.load(asset.id, { thumbnail: false, download: true })
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `design-image-${asset.id}.png`
      anchor.click()
    } catch (error) {
      msgError(safeRequestMessage(error))
    }
  }

  async function initialize() {
    initializing.value = true
    const initializeGeneration = conversationGeneration
    try {
      await Promise.all([loadConfig(), loadSessions({ requestGeneration: initializeGeneration })])
      const activeResponse = await getActiveJob()
      const restored = restoreActiveJob(activeResponse?.data?.job)
      if (restored) {
        jobSnapshots.set(restored.id, restored)
        activeJobs.set(restored.id, restored)
        startActivePolling(restored)
      }
      if (!acceptConversationResponse(initializeGeneration, conversationGeneration)) return
      const targetId = sessions.value[0]?.id
      if (targetId) await selectSession(targetId)
    } catch (error) {
      msgError(safeRequestMessage(error))
    } finally {
      initializing.value = false
    }
  }

  onMounted(initialize)
  onBeforeUnmount(() => {
    conversationGeneration += 1
    polling.stopPolling()
    assetUrls.cleanup()
  })

  return {
    activeJob, assets, assetUrl: assetUrls.get, baseAsset, canSend, chooseBaseAsset,
    closeLightbox, config, currentSession, currentSessionId, downloadAsset, draftAttachments,
    drawerOpen, initializing, jobs, lightboxAsset, lightboxUrl, loadMoreSessions: () => loadSessions({ append: true }),
    messages, newConversation, nextCursor, openLightbox, prompt, quality, removeAttachment,
    retry, selectSession, sendInFlight, sessions, sessionsLoading, size, submit,
    uploadInFlight, uploadReference,
  }
}
