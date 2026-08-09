import { computed, onBeforeUnmount, onMounted, reactive } from 'vue'
import {
  applyBootstrap,
  applySubmitFailure,
  canGenerate,
  emptyPortalState,
  ensureRequestId,
  generationStatusText,
  hasActiveGenerations,
  markInputsChanged,
  mergeGeneration,
  requiredOptionsComplete,
  selectProductState,
} from '../state.js'
import { useCustomerImageAssets } from './useCustomerImageAssets.js'

const POLL_DELAY_MS = 2500
const INVALID_LINK = '此链接已失效，请联系您的业务经理重新获取。'

export function useCustomerImagePortal({
  api,
  lifecycle = { onMounted, onBeforeUnmount },
  urlApi = URL,
  schedule = setTimeout,
  cancelSchedule = clearTimeout,
  scrollResultIntoView = () => {},
  clearInvite = () => {},
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
    return current ? generationStatusText(current.status) : ''
  })
  const generateEnabled = computed(() => canGenerate(state, selectedProduct.value))
  const generateHint = computed(() => {
    if (!state.logo?.id) return '请先上传品牌 LOGO'
    if (!requiredOptionsComplete(selectedProduct.value, state.selections)) return '请完成必选参数'
    if (state.quota.remaining <= 0) return '本次邀请的生成额度已用完，历史结果仍可查看下载'
    if (state.submitting) return '正在提交，请稍候'
    return ''
  })

  async function bootstrap() {
    const epoch = portalEpoch
    state.loading = true
    state.error = ''
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
        state.resultAnnouncement = `${completed.product_name || '产品'}效果图已生成`
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
    state.error = ''
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
    state.error = ''
    try {
      const response = await uploadLogo(file)
      if (epoch !== portalEpoch) return
      state.logo = response.data
      await assets.loadLogo(state.logo)
      Object.assign(state, markInputsChanged(state))
      state.notice = 'LOGO 已更新，可以继续选择参数。'
    } catch (error) {
      if (epoch !== portalEpoch) return
      if (isUnauthorized(error)) invalidateInvite()
      else state.error = customerSafeError(error, 'LOGO 上传失败，请检查图片后重试')
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
    state.error = ''
    state.notice = ''
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
      state.notice = generationStatusText(generation.status)
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
              customerSafeError(refreshError, '产品设置更新失败，请检查网络后重试'),
            ))
          }
        }
      } else if (isQuotaOrLogoConflict(error)) {
        await refreshContextBestEffort()
        if (epoch === portalEpoch) state.error = customerSafeError(error, '请确认额度和 LOGO 后重试')
      } else {
        Object.assign(state, applySubmitFailure(
          state,
          customerSafeError(error, '生图服务暂时不可用，本次设置已保留，请稍后重试'),
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
    anchor.download = `${generation.product_name || '产品效果图'}-${generation.id}.png`
    anchor.click()
  }

  function handlePublicError(error) {
    if (isUnauthorized(error)) return invalidateInvite()
    state.view = state.products.length ? state.view : 'error'
    state.error = customerSafeError(error, '页面暂时无法加载，请检查网络后重试')
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
    state.notice = '产品设置已更新，请确认最新参数后再次生成'
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
      error: '',
      notice: INVALID_LINK,
      resultAnnouncement: '',
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

function customerSafeError(error, fallback) {
  const status = error.response?.status
  const detail = String(error.response?.data?.detail || '')
  if (status === 429) return '操作过于频繁，请稍候一分钟再试'
  if (status === 413) return 'LOGO 图片过大，请压缩后重新上传'
  if (status === 400 && /logo|image|upload/i.test(detail)) return 'LOGO 图片无法识别，请更换 PNG、JPG 或 WebP 图片'
  if (status === 409 && /quota/i.test(detail)) return '本次邀请的生成额度已用完，历史结果仍可查看下载'
  if (status === 409 && /settings changed|Product settings/i.test(detail)) return '产品设置已更新，请重新选择参数后生成'
  if (status === 409 && /logo/i.test(detail)) return '请先上传品牌 LOGO'
  if (status === 503) return '生图服务暂时不可用，本次设置已保留，请稍后重试'
  return fallback
}
