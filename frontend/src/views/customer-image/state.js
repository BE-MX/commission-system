const ACTIVE_STATUSES = new Set(['queued', 'running'])

export function emptyPortalState() {
  return {
    view: 'loading',
    loading: true,
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
    notice: '',
  }
}

export function defaultSelections(product) {
  return Object.fromEntries((product?.options || [])
    .filter(option => option.default_value !== null && option.default_value !== undefined)
    .map(option => [
      option.key,
      option.control_type === 'boolean'
        ? option.default_value === true || option.default_value === 'true'
        : option.default_value,
    ]))
}

export function applyBootstrap(current, { context, products, generations }) {
  const visibleProducts = Array.isArray(products) ? products : []
  const history = [...(generations || [])].sort(compareGenerationNewest)
  const onlyProduct = visibleProducts.length === 1 ? visibleProducts[0] : null
  const latestResult = history.find(item => item.status === 'succeeded') || history[0]
  return {
    ...current,
    loading: false,
    context,
    products: visibleProducts,
    selectedProductId: onlyProduct?.id ?? null,
    selections: onlyProduct ? defaultSelections(onlyProduct) : {},
    logo: context?.current_logo ?? null,
    quota: context?.quota ?? { total: 0, used: 0, remaining: 0 },
    generations: history,
    previewGenerationId: latestResult?.id ?? null,
    view: onlyProduct ? 'editor' : visibleProducts.length ? 'catalog' : 'empty',
    notice: visibleProducts.length
      ? ''
      : '当前没有可设计的产品，请联系您的业务经理。',
    error: '',
  }
}

export function selectProductState(current, product) {
  return {
    ...current,
    view: 'editor',
    selectedProductId: product.id,
    selections: defaultSelections(product),
    requirement: '',
    requestId: null,
    error: '',
  }
}

export function requiredOptionsComplete(product, selections) {
  return (product?.options || []).every(option => {
    if (!option.required) return true
    const value = selections?.[option.key]
    return value !== undefined && value !== null && value !== ''
  })
}

export function canGenerate(current, product) {
  return Boolean(
    current.logo?.id
    && current.quota?.remaining > 0
    && !current.submitting
    && requiredOptionsComplete(product, current.selections),
  )
}

export function ensureRequestId(current, createId = defaultRequestId) {
  return current.requestId
    ? current
    : { ...current, requestId: createId() }
}

export function markInputsChanged(current) {
  return { ...current, requestId: null, error: '' }
}

export function applySubmitFailure(current, message) {
  return { ...current, submitting: false, error: message, notice: '' }
}

export function generationStatusText(status) {
  return {
    queued: '已提交，可以关闭页面，结果会保留在这里',
    running: '正在生成，通常需要几十秒到数分钟',
    succeeded: '效果图已完成，可以预览和下载',
    failed: '生成未完成，本次设置已保留，可以重试',
  }[status] || '状态正在更新'
}

function compareGenerationNewest(left, right) {
  return String(right.created_at || '').localeCompare(String(left.created_at || ''))
}

export function mergeGeneration(generations, generation) {
  return [generation, ...(generations || []).filter(item => item.id !== generation.id)]
    .sort(compareGenerationNewest)
}

export function hasActiveGenerations(generations) {
  return (generations || []).some(item => ACTIVE_STATUSES.has(item.status))
}

function defaultRequestId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = new Uint32Array(4)
  globalThis.crypto?.getRandomValues?.(bytes)
  return [...bytes].map(value => value.toString(36)).join('-') || `${Date.now()}`
}
