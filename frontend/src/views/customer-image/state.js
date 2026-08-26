import { customerImageMessage } from './i18n.js'

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
    error: null,
    notice: null,
    resultAnnouncement: null,
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
      ? null
      : customerImageMessage('portal.empty.detail'),
    error: null,
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
    error: null,
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
  return { ...current, requestId: null, error: null }
}

export function applySubmitFailure(current, message) {
  return { ...current, submitting: false, error: message, notice: null }
}

export function generationStatusMessage(status) {
  return {
    queued: customerImageMessage('generation.queued.detail'),
    running: customerImageMessage('generation.running.detail'),
    succeeded: customerImageMessage('generation.succeeded.detail'),
    failed: customerImageMessage('generation.failed.detail'),
  }[status] || customerImageMessage('generation.processing.detail')
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
