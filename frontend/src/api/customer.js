import request from './request'

export function getSnapshotList(params) {
  return request.get('/customer/snapshot/list', { params, showLoading: false })
}

export function createSnapshot(data) {
  return request.post('/customer/snapshot', data, { loadingText: '正在保存...' })
}

export function completeSnapshot(snapshotId, data) {
  return request.put(`/customer/snapshot/${snapshotId}/complete`, data, { loadingText: '正在保存...' })
}

export function resetSnapshot(snapshotId, data) {
  return request.put(`/customer/snapshot/${snapshotId}/reset`, data, { loadingText: '正在重置...' })
}

export function importSnapshots(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/customer/snapshot/import', formData, { loadingText: '正在导入...' })
}

export function downloadTemplate() {
  return `/api/v1/customer/snapshot/template`
}

export function autoMatchSnapshots() {
  return request.post('/customer/snapshot/auto-match', null, { loadingText: '正在自动匹配...' })
}
