export function exportCommissionDetails(batchId, groupBy) {
  const params = groupBy ? `?group_by=${groupBy}` : ''
  return `/api/v1/report/commission/${batchId}/export${params}`
}

export function exportSalespersonSummary(batchId) {
  return `/api/v1/report/commission/${batchId}/salesperson-summary`
}

export function exportSupervisorSummary(batchId) {
  return `/api/v1/report/commission/${batchId}/supervisor-summary`
}
