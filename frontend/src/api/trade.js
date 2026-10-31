import { tradeClient as api } from './clients'
export const getRoster = (params, config = {}) => api.get('/roster', { ...config, params })
export const updateRoster = (id, body) => api.put(`/roster/${id}`, body)
export const getDepartments = (config = {}) => api.get('/departments', config)
export const getProjectionStatus = (config = {}) => api.get('/projection-status', config)
