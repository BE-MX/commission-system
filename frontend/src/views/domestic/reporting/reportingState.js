export const REPORTING_PENDING_KEY = 'ark_mobile_domestic_pending_v1'

export function reportingPendingStorageKey(userId) {
  return `${REPORTING_PENDING_KEY}:${String(userId)}`
}

export const BLOCK_MESSAGES = {
  SIGN_INVALID: '二维码无效，请扫描内贸流转卡',
  ITEM_NOT_FOUND: '找不到这张卡对应的订单明细',
  NO_ROUTE: '这个产品还没配置工艺路线，请联系跟单',
  ORDER_TERMINATED: '订单已终止或删除，不能报工',
  ORDER_DRAFT: '订单仍是草稿，请跟单提交后再报工',
  UNIT_QR_REQUIRED: '当前账号是逐件模式，请扫描单件二维码',
  ALL_DONE: '这批货所有工序都已完成',
  NOT_ASSIGNED: '当前账号没有分配到可报工工序',
  NOTHING_REPORTABLE: '上一道工序还没有可接数量，请稍后再扫',
}

const UNIT_PATTERN = /^ARK-DU:(\d+):([a-f0-9]{8})$/i
const ITEM_PATTERN = /^ARK-D:(\d+):([a-f0-9]{8})$/i

export function parseDomesticReportingCode(input) {
  const raw = String(input || '').replace(/\0/g, '').trim()
  const unit = raw.match(UNIT_PATTERN)
  const item = raw.match(ITEM_PATTERN)
  const matched = unit || item
  if (!matched) return null
  const id = Number(matched[1])
  if (!Number.isSafeInteger(id) || id < 1) return null
  return {
    type: unit ? 'unit' : 'item',
    id,
    sign: matched[2].toLowerCase(),
    raw,
  }
}

export function buildMobileReportPayload(scan, code, qty, requestId) {
  const nextStep = scan?.next_step || {}
  const body = {
    item_id: scan?.item_id,
    progress_id: nextStep.progress_id,
    qty,
    request_id: requestId,
  }
  if (scan?.report_mode === 'unit') {
    body.unit_id = scan.unit_id
    body.unit_sign = code.sign
  }
  return body
}

export function httpStatus(error) {
  return Number(error?.response?.status || 0)
}

export function isDefinitiveSubmitFailure(error) {
  const status = httpStatus(error)
  return status >= 400 && status < 500 && !isReportingAuthError(error)
}

export function isReportingAuthError(error) {
  const status = httpStatus(error)
  const detail = error?.response?.data?.detail
  return status === 401 || (status === 403 && detail === 'Not authenticated')
}

export function reportingErrorMessage(error, fallback = '网络异常，请稍后重试') {
  const detail = error?.response?.data?.detail
  if (detail && typeof detail === 'object') return detail.message || fallback
  return detail || error?.response?.data?.message || error?.message || fallback
}

export function collectRequirementImagePaths(scan) {
  return ['hairstyle_images', 'color_images', 'style_images', 'remark_images']
    .flatMap(key => Array.isArray(scan?.[key]) ? scan[key] : [])
    .filter(Boolean)
}
