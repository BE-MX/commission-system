import { integrationClient } from './clients'

export const listIntegrationApps = () => integrationClient.get('/apps')
export const searchIntegrationAppCandidates = (params) => integrationClient.get('/user-candidates', { params })
export const createIntegrationApp = (payload) => integrationClient.post('/apps', payload)
export const rotateIntegrationApp = (appId, currentTokenSuffix) => integrationClient.post(
  `/apps/${appId}/rotate`,
  { current_token_suffix: currentTokenSuffix },
)
export const revokeIntegrationApp = (appId) => integrationClient.delete(`/apps/${appId}`)
