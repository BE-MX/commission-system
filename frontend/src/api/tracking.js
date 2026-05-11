import request from './request'

export function getShipmentList(params) {
  return request.get('/tracking/shipments', { params, showLoading: false })
}

export function uploadOCR(formData) {
  return request.post('/tracking/upload-ocr', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 35000,
    loadingText: '正在识别运单信息...',
  })
}

export function checkWaybill(waybillNo) {
  return request.get('/tracking/waybills/check', {
    params: { waybill_no: waybillNo },
    showLoading: false,
  })
}

export function createWaybill(data) {
  return request.post('/tracking/waybills', data, {
    loadingText: '正在提交运单...',
  })
}

export function getShipmentDetail(waybillNo) {
  return request.get(`/tracking/shipments/${waybillNo}`, { showLoading: false })
}

export function refreshShipment(waybillNo) {
  return request.post(`/tracking/shipments/${waybillNo}/refresh`, null, {
    loadingText: '正在刷新物流状态...',
  })
}

export function getTrackingStats() {
  return request.get('/tracking/stats', { showLoading: false })
}

export function createStaging(data) {
  return request.post('/tracking/staging', data, { loadingText: '正在提交...' })
}

export function triggerScanStaging() {
  return request.post('/tracking/scan-staging', null, { loadingText: '正在扫描...' })
}

export function triggerPoll() {
  return request.post('/tracking/poll', null, {
    timeout: 300000,
    loadingText: '正在轮询物流状态...',
  })
}
