import { designClient as designApi } from './clients'

// --- Request (预约单) ---

export function submitRequest(data) {
  return designApi.post('/requests', data, { loadingText: '正在提交...' })
}

export function getRequests(params) {
  return designApi.get('/requests', { params, showLoading: false })
}

export function getRequestDetail(id) {
  return designApi.get(`/requests/${id}`, { showLoading: false })
}

export function auditRequest(id, data) {
  return designApi.post(`/requests/${id}/audit`, data, { loadingText: '正在提交审批...' })
}

export function actionRequest(id, data) {
  return designApi.post(`/requests/${id}/action`, data, { loadingText: '正在处理...' })
}

// --- Gantt / Tasks ---

export function getGanttData(params) {
  return designApi.get('/gantt', { params, showLoading: false })
}

export function getTaskList(params) {
  return designApi.get('/tasks', { params, showLoading: false })
}

export function rescheduleTask(taskId, data) {
  return designApi.put(`/tasks/${taskId}/reschedule`, data, { loadingText: '正在调整排期...' })
}

// --- Unavailable Dates ---

export function getUnavailableDates() {
  return designApi.get('/unavailable-dates', { showLoading: false })
}

export function createUnavailableDates(data) {
  return designApi.post('/unavailable-dates', data)
}

export function deleteUnavailableDate(date) {
  return designApi.delete(`/unavailable-dates/${date}`)
}

// --- Capacity & Config ---

export function getCapacity() {
  return designApi.get('/capacity', { showLoading: false })
}

export function updateCapacity(data) {
  return designApi.put('/capacity', data)
}

export function getSchedulingMode() {
  return designApi.get('/scheduling-mode', { showLoading: false })
}

export function updateSchedulingMode(data) {
  return designApi.put('/scheduling-mode', data)
}

// --- Conflict Check ---

export function checkConflict(params) {
  return designApi.get('/conflict-check', { params, showLoading: false })
}

// --- Designers ---

export function getDesigners() {
  return designApi.get('/designers', { showLoading: false })
}

export function createDesigner(data) {
  return designApi.post('/designers', data, { loadingText: '正在保存...' })
}

export function updateDesigner(id, data) {
  return designApi.put(`/designers/${id}`, data, { loadingText: '正在保存...' })
}

// --- Audit Logs ---

export function getAuditLogs(requestId) {
  return designApi.get(`/audit-logs/${requestId}`, { showLoading: false })
}

// --- Export ---

export function exportTasksExcel(params) {
  return designApi.get('/export/tasks', {
    params,
    responseType: 'blob',
    showLoading: false,
  })
}

// --- Stats ---

export function getDesignStats(params) {
  return designApi.get('/stats', { params, showLoading: false })
}

// --- Import ---

export function importRequests(formData, params) {
  return designApi.post('/import/requests', formData, {
    params,
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '正在导入...',
  })
}

// --- Attachments ---

export function uploadAttachment(requestId, file, params = {}) {
  const formData = new FormData()
  formData.append('file', file)
  return designApi.post(`/requests/${requestId}/attachments`, formData, {
    params,
    headers: { 'Content-Type': 'multipart/form-data' },
    loadingText: '正在上传...',
  })
}

export function getAttachments(requestId) {
  return designApi.get(`/requests/${requestId}/attachments`, { showLoading: false })
}

export function deleteAttachment(attachmentId) {
  return designApi.delete(`/attachments/${attachmentId}`, { loadingText: '正在删除...' })
}

export function getAttachmentDownloadUrl(attachmentId) {
  return `/api/design/attachments/${attachmentId}/download`
}

export function updateExpectDate(requestId, data) {
  return designApi.put(`/requests/${requestId}/expect-date`, data, { loadingText: '正在更新...' })
}

export function updateRequestRemark(requestId, data) {
  return designApi.put(`/requests/${requestId}/remark`, data, { loadingText: '正在保存...' })
}

export function updateRequestShootType(requestId, data) {
  return designApi.put(`/requests/${requestId}/shoot-type`, data, { loadingText: '正在保存...' })
}

export function updateTaskShootType(taskId, data) {
  return designApi.put(`/tasks/${taskId}/shoot-type`, data, { loadingText: '正在保存...' })
}

export function triggerShootReminderScan() {
  return designApi.post('/scan-shoot-reminders', null, { loadingText: '正在扫描...' })
}

export default designApi
