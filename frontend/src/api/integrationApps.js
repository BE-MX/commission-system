import { integrationClient } from './clients'

export const listIntegrationApps = (config = {}) => integrationClient.get('/apps', { ...config, showLoading: false })
export const searchIntegrationAppCandidates = (params, config = {}) => integrationClient.get('/user-candidates', { ...config, params, showLoading: false })
export const createIntegrationApp = (payload) => integrationClient.post('/apps', payload)
export const rotateIntegrationApp = (appId, currentTokenSuffix) => integrationClient.post(
  `/apps/${appId}/rotate`,
  { current_token_suffix: currentTokenSuffix },
)
export const revokeIntegrationApp = (appId) => integrationClient.delete(`/apps/${appId}`)
