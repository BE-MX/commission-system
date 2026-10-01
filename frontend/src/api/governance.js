/**
 * 数据概念治理 API client
 */
import { governanceClient } from './clients'

// ── 概念 CRUD ────────────────────────────────────────────

export function listConcepts(params, config = {}) {
  return governanceClient.get('/concepts', { ...config, params })
}

export function getConcept(conceptId) {
  return governanceClient.get(`/concepts/${conceptId}`)
}

export function createConcept(data) {
  return governanceClient.post('/concepts', data)
}

export function updateConcept(conceptId, data) {
  return governanceClient.put(`/concepts/${conceptId}`, data)
}

export function transitionStatus(conceptId, payload) {
  return governanceClient.patch(`/concepts/${conceptId}/status`, payload)
}

export function getGovernanceStats(config = {}) {
  return governanceClient.get('/stats', { ...config, showLoading: false })
}

// ── 关联关系 ──────────────────────────────────────────────

export function listRelationships(conceptId) {
  return governanceClient.get(`/concepts/${conceptId}/relationships`)
}

export function createRelationship(conceptId, data) {
  return governanceClient.post(`/concepts/${conceptId}/relationships`, data)
}

export function deleteRelationship(conceptId, relId) {
  return governanceClient.delete(`/concepts/${conceptId}/relationships/${relId}`)
}

// ── 图谱 ──────────────────────────────────────────────────

export function getConceptGraph(config = {}) {
  return governanceClient.get('/graph', { ...config, showLoading: false })
}

// ── 变更记录 ──────────────────────────────────────────────

export function listChangeLogs(params, config = {}) {
  return governanceClient.get('/change-logs', { ...config, params })
}

export function getChangeDiff(logId) {
  return governanceClient.get(`/change-logs/${logId}/diff`)
}

export function rollbackToVersion(logId) {
  return governanceClient.post(`/change-logs/${logId}/rollback`)
}

// ── 导入/导出 ─────────────────────────────────────────────

export function importConcepts(data) {
  return governanceClient.post('/import', data)
}

export function exportConcepts(format = 'json') {
  return governanceClient.get('/export', { params: { format } })
}

export function seedGovernanceData() {
  return governanceClient.post('/seed')
}
