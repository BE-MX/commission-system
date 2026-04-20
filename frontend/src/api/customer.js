import request from './request'

export function getSnapshotList(params) {
  return request.get('/customer/snapshot/list', { params })
}

export function createSnapshot(data) {
  return request.post('/customer/snapshot', data)
}

export function completeSnapshot(snapshotId, data) {
  return request.put(`/customer/snapshot/${snapshotId}/complete`, data)
}

export function resetSnapshot(snapshotId, data) {
  return request.put(`/customer/snapshot/${snapshotId}/reset`, data)
}

export function importSnapshots(file) {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/customer/snapshot/import', formData)
}

export function downloadTemplate() {
  return `/api/v1/customer/snapshot/template`
}
