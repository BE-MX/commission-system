import { aiGatewayClient as client } from './clients'

export const gatewayOptions = () => client.get('/options')
export const listGatewayApps = (params, config = {}) => client.get('/apps', { ...config, params })
export const createGatewayApp = data => client.post('/apps', data)
export const updateGatewayApp = (id, data) => client.patch(`/apps/${id}`, data)
export const rotateGatewayKey = id => client.post(`/apps/${id}/rotate-key`)
export const listGatewayRequests = (id, params, config = {}) => client.get(`/apps/${id}/requests`, { ...config, params })
export const resolveGatewayRequest = (id, requestId, reason) => client.post(`/apps/${id}/requests/${requestId}/resolve`, { reason })
