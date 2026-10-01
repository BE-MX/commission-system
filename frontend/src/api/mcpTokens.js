import { mcpClient } from './clients'

export const listMcpTokens = (config = {}) => mcpClient.get('/tokens', { ...config, showLoading: false })
export const searchMcpTokenCandidates = (params, config = {}) => mcpClient.get('/token-candidates', { ...config, params, showLoading: false })
export const issueMcpToken = (payload) => mcpClient.post('/tokens', payload)
export const rotateMcpToken = (tokenId) => mcpClient.post(`/tokens/${tokenId}/rotate`)
export const revokeMcpToken = (tokenId) => mcpClient.delete(`/tokens/${tokenId}`)
