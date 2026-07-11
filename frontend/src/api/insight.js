import { insightClient as insightApi } from './clients'

// ── 报告 ──────────────────────────────────────────────
export function listReports(params) {
  return insightApi.get('/reports', { params, showLoading: false })
}

export function getReport(id) {
  return insightApi.get(`/reports/${id}`, { showLoading: false })
}

export function getReportHtml(id) {
  return insightApi.get(`/reports/${id}/html`, { showLoading: false, responseType: 'text' })
}

export function regenerateReport(id) {
  return insightApi.post(`/reports/${id}/regenerate`, null, { loadingText: '正在重新生成...' })
}

export function triggerReportGeneration(reportType) {
  return insightApi.post(`/reports/generate/${reportType}`, null, { loadingText: '正在生成报告...' })
}

// ── 信源 ──────────────────────────────────────────────
export function listSources(params) {
  return insightApi.get('/sources', { params, showLoading: false })
}

export function getSource(id) {
  return insightApi.get(`/sources/${id}`, { showLoading: false })
}

export function createSource(data) {
  return insightApi.post('/sources', data, { loadingText: '正在保存...' })
}

export function updateSource(id, data) {
  return insightApi.put(`/sources/${id}`, data, { loadingText: '正在保存...' })
}

export function deleteSource(id) {
  return insightApi.delete(`/sources/${id}`, { loadingText: '正在禁用...' })
}

export function testSource(id) {
  return insightApi.post(`/sources/${id}/test`, null, { loadingText: '正在测试连通性...' })
}

export function collectSource(id) {
  return insightApi.post(`/sources/${id}/collect`, null, { loadingText: '正在采集...' })
}

// ── 情报条目 ──────────────────────────────────────────
export function listItems(params) {
  return insightApi.get('/items', { params, showLoading: false })
}

export function getItem(id) {
  return insightApi.get(`/items/${id}`, { showLoading: false })
}

export function toggleItemFeature(id) {
  return insightApi.patch(`/items/${id}/feature`, null, { showLoading: false })
}

export function updateItemStatus(id, status) {
  return insightApi.patch(`/items/${id}/status`, null, { params: { status }, showLoading: false })
}

export function uploadMd(formData) {
  return insightApi.post('/items/upload', formData, {
    loadingText: '正在上传...',
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function batchFeature(itemIds, isFeatured = true) {
  return insightApi.post('/items/batch/feature', itemIds, { loadingText: '正在更新...' })
}

export function batchStatus(itemIds, status) {
  return insightApi.post('/items/batch/status', itemIds, { params: { status }, loadingText: '正在更新...' })
}

// ── 情报速览 ──────────────────────────────────────────
export function listIntelligenceReports(params) {
  return insightApi.get('/reports/intelligence', { params, showLoading: false })
}

export function getIntelligenceHtml(id) {
  return insightApi.get(`/reports/intelligence/${id}/html`, { showLoading: false, responseType: 'text' })
}

export function generateIntelligence(data) {
  return insightApi.post('/reports/intelligence/generate', data, { loadingText: '正在生成报告...' })
}

export function deleteIntelligenceReport(id) {
  return insightApi.delete(`/reports/intelligence/${id}`, { loadingText: '正在删除...' })
}

export function pinIntelligenceReport(id, isPinned = true) {
  return insightApi.patch(`/reports/intelligence/${id}/pin`, null, { params: { is_pinned: isPinned }, showLoading: false })
}

// ── 定时规则 ──────────────────────────────────────────
export function listScheduleRules(params) {
  return insightApi.get('/schedule-rules', { params, showLoading: false })
}

export function createScheduleRule(data) {
  return insightApi.post('/schedule-rules', data, { loadingText: '正在保存...' })
}

export function updateScheduleRule(id, data) {
  return insightApi.put(`/schedule-rules/${id}`, data, { loadingText: '正在保存...' })
}

export function toggleScheduleRule(id) {
  return insightApi.patch(`/schedule-rules/${id}/toggle`, null, { showLoading: false })
}

// ── 案例库 ────────────────────────────────────────────
export function listCases(params) {
  return insightApi.get('/cases', { params, showLoading: false })
}

export function getCaseDetail(id) {
  return insightApi.get(`/cases/${id}`, { showLoading: false })
}

export function getCaseStatus(id) {
  return insightApi.get(`/cases/${id}/status`, { showLoading: false })
}

export function uploadCase(formData) {
  return insightApi.post('/cases/upload', formData, {
    loadingText: 'AI 处理中,请稍候...',
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

export function manualCreateCase(data) {
  return insightApi.post('/cases/manual', data, { loadingText: '正在发布...' })
}

export function publishCase(id, data) {
  return insightApi.post(`/cases/${id}/publish`, data, { loadingText: '正在发布...' })
}

export function updateCase(id, data) {
  return insightApi.put(`/cases/${id}`, data, { loadingText: '正在保存...' })
}

export function deleteCase(id) {
  return insightApi.delete(`/cases/${id}`, { loadingText: '正在删除...' })
}

export function toggleCaseLike(id, delta = 1) {
  return insightApi.post(`/cases/${id}/like`, null, {
    params: { delta },
    showLoading: false,
  })
}

// ── 周会纪要 ────────────────────────────────────────────
export function uploadMinutes(data) {
  return insightApi.post('/minutes/upload', data, { loadingText: 'AI 处理中,请稍候...' })
}

export function listMinutes(params) {
  return insightApi.get('/minutes', { params, showLoading: false })
}

export function getMinutesDetail(id) {
  return insightApi.get(`/minutes/${id}`, { showLoading: false })
}

export function updateTask(taskId, data) {
  return insightApi.patch(`/tasks/${taskId}`, data, { showLoading: false })
}

export function exportTasksCsv(minutesId) {
  // 端点有 JWT 鉴权，必须走 axios blob（window.open 直链不带 header 会 403）
  return insightApi.get(`/minutes/${minutesId}/tasks/export`, {
    responseType: 'blob',
    loadingText: '正在导出...',
  })
}

// ── 工作台摘要 ──────────────────────────────────────────
export function getDashboardSummary() {
  return insightApi.get('/dashboard/summary', { showLoading: false })
}

// ── 客户机会台 ──────────────────────────────────────────
export function getMyOpportunities(params) {
  return insightApi.get('/customer-opportunities/my', { params, showLoading: false })
}

export function getOpportunityStats() {
  return insightApi.get('/customer-opportunities/stats', { showLoading: false })
}

export function getOpportunityDetail(id) {
  return insightApi.get(`/customer-opportunities/${id}`, { showLoading: false })
}

export function updateOpportunityStatus(id, data) {
  return insightApi.put(`/customer-opportunities/${id}/status`, null, { params: data, loadingText: '正在更新...' })
}

export function addOpportunityFeedback(id, data) {
  return insightApi.post(`/customer-opportunities/${id}/feedback`, null, { params: data, loadingText: '正在保存...' })
}

export function getAllOpportunities(params) {
  return insightApi.get('/customer-opportunities/admin/all', { params, showLoading: false })
}

export function getUnassignedOpportunities(params) {
  return insightApi.get('/customer-opportunities/admin/unassigned', { params, showLoading: false })
}

export function assignOpportunity(id, userId) {
  return insightApi.put(`/customer-opportunities/${id}/assign`, null, { params: { user_id: userId }, loadingText: '正在分配...' })
}

// ── 客户经营雷达 ──────────────────────────────────────────
export function getRadarFocus(params) {
  return insightApi.get('/customer-radar/focus', { params, showLoading: false })
}

export function getRadarThreadCounts(params) {
  return insightApi.get('/customer-radar/threads/counts', { params, showLoading: false })
}

export function getRadarActions(params) {
  return insightApi.get('/customer-radar/actions', { params, showLoading: false })
}

export function completeRadarAction(id, params) {
  return insightApi.put(`/customer-radar/actions/${id}/complete`, null, { params, loadingText: '正在更新...' })
}

export function dismissRadarAction(id, params) {
  return insightApi.put(`/customer-radar/actions/${id}/dismiss`, null, { params, loadingText: '正在忽略...' })
}

export function snoozeRadarAction(id, params) {
  return insightApi.put(`/customer-radar/actions/${id}/snooze`, null, { params, loadingText: '正在延后...' })
}

export function submitRadarFeedback(id, data) {
  return insightApi.post(`/customer-radar/actions/${id}/feedback`, data, { loadingText: '正在保存...' })
}

export function getRadarProfile(id) {
  return insightApi.get(`/customer-radar/profiles/${id}`, { showLoading: false })
}

export function getRadarSourceRecords(id, params) {
  return insightApi.get(`/customer-radar/profiles/${id}/sources`, { params, showLoading: false })
}

export function addRadarNote(id, data) {
  return insightApi.post(`/customer-radar/profiles/${id}/notes`, data, { loadingText: '正在保存...' })
}

export function refreshRadarActions() {
  return insightApi.post('/customer-radar/actions/refresh', null, { loadingText: '正在刷新推荐...' })
}

export default insightApi
