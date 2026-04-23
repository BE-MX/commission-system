import request from './request'

export function exportCommissionDetails(batchId, groupBy) {
  const params = groupBy ? { group_by: groupBy } : {}
  return request.get(`/report/commission/${batchId}/export`, {
    params,
    responseType: 'blob',
    loadingText: '正在导出 Excel...',
  })
}

export function exportSalespersonSummary(batchId) {
  return request.get(`/report/commission/${batchId}/salesperson-summary`, {
    responseType: 'blob',
    loadingText: '正在导出 Excel...',
  })
}

export function exportSupervisorSummary(batchId) {
  return request.get(`/report/commission/${batchId}/supervisor-summary`, {
    responseType: 'blob',
    loadingText: '正在导出 Excel...',
  })
}
