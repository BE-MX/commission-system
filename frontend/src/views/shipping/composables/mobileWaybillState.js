export const numberSourceLabel = { barcode: '条码', ocr: 'AI 识别', manual: '手动' }
export function previewFingerprint(form) {
  return JSON.stringify([form.waybill_no.trim(), form.carrier, form.recipient_country.trim(), form.recipient_name.trim()])
}
export function canSubmitPreview(preview, fingerprint, form, photoToken, confirmations) {
  return !!(photoToken && form.waybill_no.trim() && form.carrier && form.recipient_country.trim()
    && preview?.preview_token && preview.can_submit && preview.format_valid && !preview.existing?.blocked
    && fingerprint === previewFingerprint(form)
    && (preview.warnings || []).every(warning => !warning.requires_confirmation || confirmations.includes(warning.code)))
}
export function syncMessage(result, carrier) {
  return ({
    found: '已查到物流轨迹',
    not_found: '承运商暂无这张运单的记录。包裹还没被揽收时很常见，提交后系统会持续跟踪。',
    failed: '物流接口暂时查不到，可以重试，也可以先提交，系统稍后自动查询。',
    unsupported: `方舟还不能查询 ${carrier} 轨迹，提交后只做登记。`,
  })[result] || '请重新同步物流信息'
}
