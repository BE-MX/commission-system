import { aiGatewayClient as client } from './clients'

export const gatewayOptions = () => client.get('/options')
export const listGatewayApps = params => client.get('/apps', { params })
export const createGatewayApp = data => client.post('/apps', data)
export const updateGatewayApp = (id, data) => client.patch(`/apps/${id}`, data)
export const rotateGatewayKey = id => client.post(`/apps/${id}/rotate-key`)
export const listGatewayRequests = (id, params) => client.get(`/apps/${id}/requests`, { params })
export const resolveGatewayRequest = (id, requestId, reason) => client.post(`/apps/${id}/requests/${requestId}/resolve`, { reason })
