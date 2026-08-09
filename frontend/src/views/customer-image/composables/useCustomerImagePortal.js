import { computed, onBeforeUnmount, onMounted, reactive } from 'vue'
import {
  createGeneration,
  getAssetBlob,
  getContext,
  getProductAssetBlob,
  listGenerations,
  listProducts,
  uploadLogo,
} from '@/api/customerImagePublic'
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
} from '../state'
import { useCustomerImageAssets } from './useCustomerImageAssets'

const POLL_DELAY_MS = 2500
const INVALID_LINK = '此链接已失效，请联系您的业务经理重新获取。'

export function useCustomerImagePortal() {
  const state = reactive(emptyPortalState())
  const assets = useCustomerImageAssets({
    fetchProductAsset: getProductAssetBlob,
    fetchInviteAsset: getAssetBlob,
  })
  let pollTimer = null
  let disposed = false

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
    state.loading = true
    state.error = ''
    try {
      const [contextResponse, productsResponse, generationsResponse] = await Promise.all([
        getContext(),
        listProducts(),
        listGenerations(),
      ])
      Object.assign(state, applyBootstrap(state, {
        context: contextResponse.data,
        products: productsResponse.data,
        generations: generationsResponse.data,
      }))
      await Promise.all([
        assets.loadProductCovers(state.products),
        assets.loadLogo(state.logo),
        assets.loadGenerationResults(state.generations),
      ])
      schedulePolling()
    } catch (error) {
      handlePublicError(error)
    } finally {
      state.loading = false
    }
  }

  async function refreshContext() {
    const response = await getContext()
    state.context = response.data
    state.quota = response.data.quota
    state.logo = response.data.current_logo
  }

  async function pollGenerations() {
    try {
      const response = await listGenerations()
      state.generations = response.data
      await assets.loadGenerationResults(state.generations)
      if (!state.previewGenerationId) {
        state.previewGenerationId = state.generations[0]?.id ?? null
      }
      await refreshContext()
    } catch (error) {
      if (error.response?.status === 401) handlePublicError(error)
    }
  }

  function schedulePolling() {
    if (disposed || pollTimer || !hasActiveGenerations(state.generations)) return
    pollTimer = setTimeout(async () => {
      pollTimer = null
      await pollGenerations()
      schedulePolling()
    }, POLL_DELAY_MS)
  }

  function chooseProduct(product) {
    Object.assign(state, selectProductState(state, product))
    state.previewGenerationId = state.generations.find(
      item => item.product_id === product.id && item.status === 'succeeded',
    )?.id ?? null
  }

  function backToCatalog() {
    if (state.products.length <= 1) return
    state.view = 'catalog'
    state.selectedProductId = null
    state.selections = {}
    state.requirement = ''
    state.requestId = null
    state.error = ''
  }

  function updateSelection(key, value) {
    state.selections = { ...state.selections, [key]: value }
    Object.assign(state, markInputsChanged(state))
  }

  function updateRequirement(value) {
    state.requirement = value
    Object.assign(state, markInputsChanged(state))
  }

  async function replaceLogo(file) {
    if (!file || state.uploadingLogo) return
    state.uploadingLogo = true
    state.error = ''
    try {
      const response = await uploadLogo(file)
      state.logo = response.data
      await assets.loadLogo(state.logo)
      Object.assign(state, markInputsChanged(state))
      state.notice = 'LOGO 已更新，可以继续选择参数。'
    } catch (error) {
      state.error = customerSafeError(error, 'LOGO 上传失败，请检查图片后重试')
    } finally {
      state.uploadingLogo = false
    }
  }

  async function submitGeneration() {
    const product = selectedProduct.value
    if (!canGenerate(state, product)) return
    Object.assign(state, ensureRequestId(state))
    state.submitting = true
    state.error = ''
    state.notice = ''
    try {
      const response = await createGeneration({
        product_id: product.id,
        config_version: product.config_version,
        request_id: state.requestId,
        selections: state.selections,
        requirement: state.requirement,
      })
      const generation = response.data
      state.generations = mergeGeneration(state.generations, generation)
      state.previewGenerationId = generation.id
      state.requestId = null
      state.notice = generationStatusText(generation.status)
      await refreshContext()
      schedulePolling()
    } catch (error) {
      if (error.response?.status === 401) {
        handlePublicError(error)
      } else {
        Object.assign(state, applySubmitFailure(
          state,
          customerSafeError(error, '生图服务暂时不可用，本次设置已保留，请稍后重试'),
        ))
      }
    } finally {
      state.submitting = false
    }
  }

  function selectGeneration(generation) {
    state.previewGenerationId = generation.id
    if (generation.status === 'succeeded') assets.loadGeneration(generation)
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
    if (error.response?.status === 401) {
      state.view = 'invalid'
      state.notice = INVALID_LINK
      state.error = ''
      state.generations = []
      stopPolling()
      return
    }
    state.view = state.products.length ? state.view : 'error'
    state.error = customerSafeError(error, '页面暂时无法加载，请检查网络后重试')
  }

  function stopPolling() {
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = null
  }

  onMounted(bootstrap)
  onBeforeUnmount(() => {
    disposed = true
    stopPolling()
    assets.clear()
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
    replaceLogo,
    selectGeneration,
    submitGeneration,
    updateRequirement,
    updateSelection,
  }
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
