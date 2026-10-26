import { perfGoalClient as client } from './clients'

const unwrap = promise => promise.then(res => res?.data ?? res)
const options = params => ({ params, showLoading: false })

/**
 * 绩效目标管理 API。后端契约见 docs（base /api/perf-goals）：
 * roster / periods(+activate) / goals / split / team-goals(+recalc) / audits /
 * overview / trend / teams / ranking / metric-orders / reports(+resend) / reports-schedule / config
 */
export const perfGoalApi = {
  roster: (config = {}) => unwrap(client.get('/roster', { ...config, ...options() })),

  periods: (config = {}) => unwrap(client.get('/periods', { ...config, ...options() })),
  createPeriod: payload => unwrap(client.post('/periods', payload)),
  activatePeriod: id => unwrap(client.post(`/periods/${id}/activate`)),
  activePeriod: (config = {}) => unwrap(client.get('/periods/active', { ...config, ...options() })),

  goals: (periodId, params, config = {}) => unwrap(client.get(`/periods/${periodId}/goals`, { ...config, ...options(params) })),
  saveGoals: (periodId, rows) => unwrap(client.put(`/periods/${periodId}/goals`, { rows })),
  splitGoals: (periodId, payload) => unwrap(client.post(`/periods/${periodId}/split`, payload)),

  teamGoals: (periodId, params, config = {}) => unwrap(client.get(`/periods/${periodId}/team-goals`, { ...config, ...options(params) })),
  saveTeamGoals: (periodId, rows) => unwrap(client.put(`/periods/${periodId}/team-goals`, { rows })),
  recalcTeamGoals: periodId => unwrap(client.post(`/periods/${periodId}/team-goals/recalc`)),

  audits: (periodId, params, config = {}) => unwrap(client.get(`/periods/${periodId}/audits`, { ...config, ...options(params) })),

  overview: (params, config = {}) => unwrap(client.get('/overview', { ...config, ...options(params) })),
  trend: (params, config = {}) => unwrap(client.get('/trend', { ...config, ...options(params) })),
  teams: (params, config = {}) => unwrap(client.get('/teams', { ...config, ...options(params) })),
  ranking: (params, config = {}) => unwrap(client.get('/ranking', { ...config, ...options(params) })),
  metricOrders: (params, config = {}) => unwrap(client.get('/metric-orders', { ...config, ...options(params) })),

  reports: (params, config = {}) => unwrap(client.get('/reports', { ...config, ...options(params) })),
  report: (id, config = {}) => unwrap(client.get(`/reports/${id}`, { ...config, ...options() })),
  resendReport: id => unwrap(client.post(`/reports/${id}/resend`)),
  reportSchedule: (config = {}) => unwrap(client.get('/reports-schedule', { ...config, ...options() })),

  getConfig: (config = {}) => unwrap(client.get('/config', { ...config, ...options() })),
  saveConfig: payload => unwrap(client.put('/config', payload)),
}
