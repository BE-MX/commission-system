/** 客户售后管理 API（/api/aftersales）。 */
import { aftersalesClient } from './clients'

export const getAfterSalesOptions = () => aftersalesClient.get('/options')
export const getAfterSalesCases = params => aftersalesClient.get('/cases', { params })
export const getAfterSalesCase = id => aftersalesClient.get(`/cases/${id}`)
export const createAfterSalesCase = data => aftersalesClient.post('/cases', data)
export const updateAfterSalesCase = (id, data) => aftersalesClient.put(`/cases/${id}`, data)
export const deleteAfterSalesCase = id => aftersalesClient.delete(`/cases/${id}`)

export const searchAfterSalesCustomers = params => aftersalesClient.get('/customers/search', { params, showLoading: false })
export const searchAfterSalesOrders = params => aftersalesClient.get('/orders/search', { params, showLoading: false })
export const searchAfterSalesProducts = params => aftersalesClient.get('/products/search', { params, showLoading: false })
export const searchAfterSalesReviewers = params => aftersalesClient.get('/reviewers/search', { params, showLoading: false })
export const searchAfterSalesPeople = params => aftersalesClient.get('/people/search', { params, showLoading: false })

export function uploadAfterSalesEvidence(caseId, file, evidenceType, summary = '') {
  const form = new FormData()
  form.append('file', file)
  form.append('evidence_type', evidenceType)
  if (summary) form.append('summary', summary)
  return aftersalesClient.post(`/cases/${caseId}/evidence`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const deleteAfterSalesEvidence = (caseId, evidenceId) => aftersalesClient.delete(`/cases/${caseId}/evidence/${evidenceId}`)
export const downloadAfterSalesEvidence = evidenceId => aftersalesClient.get(`/evidence/${evidenceId}/download`, { responseType: 'blob', showLoading: false })

export const analyzeAfterSalesCase = id => aftersalesClient.post(`/cases/${id}/analyze`)
export const saveAfterSalesDecision = (id, data) => aftersalesClient.post(`/cases/${id}/decision`, data)
export const requestAfterSalesEvidenceWaiver = (id, data) => aftersalesClient.post(`/cases/${id}/evidence-waiver/request`, data)
export const reviewAfterSalesEvidenceWaiver = (id, data) => aftersalesClient.post(`/cases/${id}/evidence-waiver/review`, data)
export const submitAfterSalesCase = (id, data) => aftersalesClient.post(`/cases/${id}/submit`, data)
export const withdrawAfterSalesCase = (id, data) => aftersalesClient.post(`/cases/${id}/withdraw`, data)
export const reviewAfterSalesCase = (id, data) => aftersalesClient.post(`/cases/${id}/review`, data)
export const transferAfterSalesApproval = (id, data) => aftersalesClient.post(`/cases/${id}/transfer`, data)
export const executeAfterSalesCase = (id, data) => aftersalesClient.post(`/cases/${id}/execute`, data)
export const closeAfterSalesCase = (id, data) => aftersalesClient.post(`/cases/${id}/close`, data)
export const reopenAfterSalesCase = (id, data) => aftersalesClient.post(`/cases/${id}/reopen`, data)
export const getAfterSalesTimeline = id => aftersalesClient.get(`/cases/${id}/timeline`)

export const getAfterSalesSopVersions = () => aftersalesClient.get('/sop/versions')
export function uploadAfterSalesSop(file, data) {
  const form = new FormData()
  form.append('file', file)
  Object.entries(data).forEach(([key, value]) => form.append(key, value))
  return aftersalesClient.post('/sop/versions', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}
export const activateAfterSalesSop = id => aftersalesClient.post(`/sop/versions/${id}/activate`)
export const retryAfterSalesNotification = id => aftersalesClient.post(`/notifications/${id}/retry`)
export const getAfterSalesAnalytics = () => aftersalesClient.get('/analytics/summary')
