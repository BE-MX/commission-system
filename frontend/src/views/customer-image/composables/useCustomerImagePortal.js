import { computed, onBeforeUnmount, onMounted, reactive } from 'vue'
import {
  applyBootstrap,
  applySubmitFailure,
  canGenerate,
  emptyPortalState,
  ensureRequestId,
  generationStatusMessage,
  hasActiveGenerations,
  markInputsChanged,
  mergeGeneration,
  requiredOptionsComplete,
  selectProductState,
} from '../state.js'
import { customerImageMessage } from '../i18n.js'
import { useCustomerImageAssets } from './useCustomerImageAssets.js'

const POLL_DELAY_MS = 2500
const INVALID_LINK = customerImageMessage('errors.invalidLink')

export function useCustomerImagePortal({
  api,
  lifecycle = { onMounted, onBeforeUnmount },
  urlApi = URL,
  schedule = setTimeout,
  cancelSchedule = clearTimeout,
  scrollResultIntoView = () => {},
  clearInvite = () => {},
  downloadFilename = generation => `generation-${generation?.id}.png`,
} = {}) {
  const {
    createGeneration,
    getAssetBlob,
    getContext,
    getProductAssetBlob,
    listGenerations,
    listProducts,
    uploadLogo,
  } = api
  const state = reactive(emptyPortalState())
  const assets = useCustomerImageAssets({
    fetchProductAsset: getProductAssetBlob,
    fetchInviteAsset: getAssetBlob,
    urlApi,
    lifecycle,
  })
  let pollTimer = null
  let disposed = false
  let portalEpoch = 0

  const selectedProduct = computed(() => (
    state.products.find(product => product.id === state.selectedProductId) ?? null
  ))
  const previewGeneration = computed(() => (
    state.generations.find(item => item.id === state.previewGenerationId) ?? null
  ))
  const generationMessage = computed(() => {
    const current = previewGeneration.value
      || state.generations.find(item => ['queued', 'running'].includes(item.status))
    return current ? generationStatusMessage(current.status) : null
  })
  const generateEnabled = computed(() => canGenerate(state, selectedProduct.value))
  const generateHint = computed(() => {
    if (!state.logo?.id) return customerImageMessage('quota.logoRequired')
    if (!requiredOptionsComplete(selectedProduct.value, state.selections)) return customerImageMessage('quota.optionsRequired')
    if (state.quota.remaining <= 0) return customerImageMessage('quota.exhausted')
    if (state.submitting) return customerImageMessage('quota.submitting')
    return null
  })

  async function bootstrap() {
    const epoch = portalEpoch
    state.loading = true
    state.error = null
    try {
      const [contextResponse, productsResponse, generationsResponse] = await Promise.all([
        getContext(),
        listProducts(),
        listGenerations(),
      ])
      if (epoch !== portalEpoch) return
      const generations = preservePendingGenerations(state.generations, generationsResponse.data)
      Object.assign(state, applyBootstrap(state, {
        context: contextResponse.data,
        products: productsResponse.data,
        generations,
      }))
      await Promise.all([
        assets.loadProductCovers(state.products),
        assets.loadLogo(state.logo),
        assets.loadGenerationResults(state.generations),
      ])
      if (epoch !== portalEpoch) return
      schedulePolling()
    } catch (error) {
      if (epoch !== portalEpoch) return
      handlePublicError(error)
    } finally {
      state.loading = false
    }
  }

  async function refreshContext() {
    const epoch = portalEpoch
    try {
      const response = await getContext()
      if (epoch !== portalEpoch) return false
      state.context = response.data
      state.quota = response.data.quota
      state.logo = response.data.current_logo
      await assets.loadLogo(state.logo)
      return epoch === portalEpoch
    } catch (error) {
      if (epoch !== portalEpoch) return false
      if (isUnauthorized(error)) {
        invalidateInvite()
        return false
      }
      throw error
    }
  }

  async function refreshContextBestEffort() {
    try { return await refreshContext() } catch { return false }
  }

  async function pollGenerations() {
    const epoch = portalEpoch
    const activeIds = new Set(state.generations
      .filter(item => ['queued', 'running'].includes(item.status))
      .map(item => item.id))
    try {
      const response = await listGenerations()
      if (epoch !== portalEpoch) return
      state.generations = preservePendingGenerations(state.generations, response.data)
      await assets.loadGenerationResults(state.generations)
      if (epoch !== portalEpoch) return
      const completed = state.generations.find(
        item => activeIds.has(item.id) && item.status === 'succeeded',
      )
      if (completed) {
        state.previewGenerationId = completed.id
        state.resultAnnouncement = customerImageMessage('generation.completed.announcement', {
          product: completed.product_name || '',
        })
        scrollResultIntoView(completed.id)
      }
      if (!state.previewGenerationId) {
        state.previewGenerationId = state.generations[0]?.id ?? null
      }
      await refreshContextBestEffort()
    } catch (error) {
      if (epoch !== portalEpoch) return
      handlePublicError(error)
    }
  }

  function schedulePolling() {
    if (disposed || pollTimer || !hasActiveGenerations(state.generations)) return
    pollTimer = schedule(async () => {
      pollTimer = null
      await pollGenerations()
      schedulePolling()
    }, POLL_DELAY_MS)
  }

  function chooseProduct(product) {
    if (state.submitting) return
    Object.assign(state, selectProductState(state, product))
    state.previewGenerationId = state.generations.find(
      item => item.product_id === product.id && item.status === 'succeeded',
    )?.id ?? null
  }

  function backToCatalog() {
    if (state.submitting) return
    if (state.products.length <= 1) return
    state.view = 'catalog'
    state.selectedProductId = null
    state.selections = {}
    state.requirement = ''
    state.requestId = null
    state.error = null
  }

  function updateSelection(key, value) {
    if (state.submitting) return
    state.selections = { ...state.selections, [key]: value }
    Object.assign(state, markInputsChanged(state))
  }

  function updateRequirement(value) {
    if (state.submitting) return
    state.requirement = value
    Object.assign(state, markInputsChanged(state))
  }

  async function replaceLogo(file) {
    if (!file || state.uploadingLogo || state.submitting) return
    const epoch = portalEpoch
    state.uploadingLogo = true
    state.error = null
    try {
      const response = await uploadLogo(file)
      if (epoch !== portalEpoch) return
      state.logo = response.data
      await assets.loadLogo(state.logo)
      Object.assign(state, markInputsChanged(state))
      state.notice = customerImageMessage('settings.logoUpdated')
    } catch (error) {
      if (epoch !== portalEpoch) return
      if (isUnauthorized(error)) invalidateInvite()
      else state.error = customerSafeError(error, 'errors.logoUploadFailed')
    } finally {
      if (epoch === portalEpoch) state.uploadingLogo = false
    }
  }

  async function submitGeneration() {
    if (state.submitting) return
    const product = selectedProduct.value
    if (!canGenerate(state, product)) return
    Object.assign(state, ensureRequestId(state))
    state.submitting = true
    state.error = null
    state.notice = null
    const epoch = portalEpoch
    const payload = {
      product_id: product.id,
      config_version: product.config_version,
      request_id: state.requestId,
      selections: { ...state.selections },
      requirement: state.requirement,
    }
    try {
      const response = await createGeneration(payload)
      if (epoch !== portalEpoch) return
      const generation = response.data
      state.generations = mergeGeneration(state.generations, generation)
      state.previewGenerationId = generation.id
      state.requestId = null
      state.notice = generationStatusMessage(generation.status)
      await refreshContextBestEffort()
      schedulePolling()
    } catch (error) {
      if (epoch !== portalEpoch) return
      if (isUnauthorized(error)) {
        invalidateInvite()
      } else if (isSettingsConflict(error)) {
        try {
          await refreshSettings(product.id)
        } catch (refreshError) {
          if (isUnauthorized(refreshError)) {
            invalidateInvite()
          } else {
            Object.assign(state, applySubmitFailure(
              state,
              customerSafeError(refreshError, 'errors.settingsRefreshFailed'),
            ))
          }
        }
      } else if (isQuotaOrLogoConflict(error)) {
        await refreshContextBestEffort()
        if (epoch === portalEpoch) state.error = customerSafeError(error, 'errors.generationConflict')
      } else {
        Object.assign(state, applySubmitFailure(
          state,
          customerSafeError(error, 'errors.generationFailed'),
        ))
      }
    } finally {
      if (epoch === portalEpoch) state.submitting = false
    }
  }

  async function selectGeneration(generation) {
    state.previewGenerationId = generation.id
    if (generation.status !== 'succeeded') return
    try {
      await assets.loadGeneration(generation)
    } catch (error) {
      handlePublicError(error)
    }
  }

  function downloadGeneration(generation) {
    const url = assets.generationUrls[generation?.id]
    if (!url) return
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = downloadFilename(generation)
    anchor.click()
  }

  function handlePublicError(error) {
    if (isUnauthorized(error)) return invalidateInvite()
    state.view = state.products.length ? state.view : 'error'
    state.error = customerSafeError(error, 'errors.pageLoadFailed')
  }

  function stopPolling() {
    if (pollTimer) cancelSchedule(pollTimer)
    pollTimer = null
  }

  async function refreshSettings(productId) {
    const epoch = portalEpoch
    const [contextResponse, productsResponse, generationsResponse] = await Promise.all([
      getContext(),
      listProducts(),
      listGenerations(),
    ])
    if (epoch !== portalEpoch) return
    Object.assign(state, applyBootstrap(state, {
      context: contextResponse.data,
      products: productsResponse.data,
      generations: preservePendingGenerations(state.generations, generationsResponse.data),
    }))
    const refreshedProduct = state.products.find(item => item.id === productId)
    if (refreshedProduct) Object.assign(state, selectProductState(state, refreshedProduct))
    state.requestId = null
    state.notice = customerImageMessage('settings.updated')
    await Promise.all([
      assets.loadProductCovers(state.products),
      assets.loadLogo(state.logo),
      assets.loadGenerationResults(state.generations),
    ])
  }

  function invalidateInvite() {
    portalEpoch += 1
    stopPolling()
    assets.clear()
    try { clearInvite() } catch { /* State invalidation must still complete. */ }
    Object.assign(state, {
      view: 'invalid',
      loading: false,
      context: null,
      products: [],
      selectedProductId: null,
      selections: {},
      requirement: '',
      logo: null,
      quota: { total: 0, used: 0, remaining: 0 },
      generations: [],
      previewGenerationId: null,
      submitting: false,
      uploadingLogo: false,
      requestId: null,
      error: null,
      notice: INVALID_LINK,
      resultAnnouncement: null,
    })
  }

  lifecycle.onMounted(bootstrap)
  lifecycle.onBeforeUnmount(() => {
    disposed = true
    stopPolling()
    assets.dispose()
  })

  return {
    state,
    assets,
    selectedProduct,
    previewGeneration,
    generationMessage,
    generateEnabled,
    generateHint,
    backToCatalog,
    bootstrap,
    chooseProduct,
    downloadGeneration,
    pollGenerations,
    replaceLogo,
    selectGeneration,
    submitGeneration,
    updateRequirement,
    updateSelection,
  }
}

export function isSettingsConflict(error) {
  return error?.response?.status === 409
    && /settings changed|Product settings/i.test(String(error.response?.data?.detail || ''))
}

export function isUnauthorized(error) {
  return error?.response?.status === 401
}

export function isQuotaOrLogoConflict(error) {
  if (error?.response?.status !== 409) return false
  return /quota|logo/i.test(String(error.response?.data?.detail || ''))
}

export function preservePendingGenerations(current, incoming) {
  const listed = Array.isArray(incoming) ? incoming : []
  const listedIds = new Set(listed.map(item => item.id))
  const pending = (current || []).filter(
    item => ['queued', 'running'].includes(item.status) && !listedIds.has(item.id),
  )
  return [...listed, ...pending].sort((left, right) => (
    String(right.created_at || '').localeCompare(String(left.created_at || ''))
  ))
}

function customerSafeError(error, fallbackKey) {
  const status = error.response?.status
  const detail = String(error.response?.data?.detail || '')
  if (status === 429) return customerImageMessage('errors.rateLimited')
  if (status === 413) return customerImageMessage('errors.uploadTooLarge')
  if (status === 400 && /logo|image|upload/i.test(detail)) return customerImageMessage('errors.uploadInvalid')
  if (status === 409 && /quota/i.test(detail)) return customerImageMessage('errors.quotaExhausted')
  if (status === 409 && /settings changed|Product settings/i.test(detail)) return customerImageMessage('errors.settingsChanged')
  if (status === 409 && /logo/i.test(detail)) return customerImageMessage('errors.logoRequired')
  if (status === 503) return customerImageMessage('errors.serviceUnavailable')
  return customerImageMessage(fallbackKey)
}
