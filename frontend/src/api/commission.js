import request from './request'

export function createBatch(data) {
  return request.post('/commission/batch', data)
}

export function getBatchList(params) {
  return request.get('/commission/batch/list', { params })
}

export function calculateBatch(batchId) {
  return request.post(`/commission/batch/${batchId}/calculate`)
}

export function getBatchDetails(batchId, params) {
  return request.get(`/commission/batch/${batchId}/details`, { params })
}

export function confirmBatch(batchId, data) {
  return request.post(`/commission/batch/${batchId}/confirm`, data)
}

export function voidBatch(batchId) {
  return request.post(`/commission/batch/${batchId}/void`)
}

export function getBatchSummary(batchId) {
  return request.get(`/commission/batch/${batchId}/summary`)
}
