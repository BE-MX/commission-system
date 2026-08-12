import { mcpClient } from './clients'

export const listMcpTokens = () => mcpClient.get('/tokens')
export const searchMcpTokenCandidates = (params) => mcpClient.get('/token-candidates', { params })
export const issueMcpToken = (payload) => mcpClient.post('/tokens', payload)
export const rotateMcpToken = (tokenId) => mcpClient.post(`/tokens/${tokenId}/rotate`)
export const revokeMcpToken = (tokenId) => mcpClient.delete(`/tokens/${tokenId}`)
