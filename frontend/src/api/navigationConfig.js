import { systemClient } from './clients'
const base = '/navigation-config'
export const getNavigationCatalog = () => systemClient.get(`${base}/catalog`)
export const getNavigationDraft = () => systemClient.get(`${base}/draft`)
export const saveNavigationDraft = (data) => systemClient.put(`${base}/draft`, data)
export const publishNavigationDraft = (data) => systemClient.post(`${base}/publish`, data)
export const getNavigationVersions = () => systemClient.get(`${base}/versions`)
export const restoreNavigationVersion = (id, data) => systemClient.post(`${base}/versions/${encodeURIComponent(id)}/restore-draft`, data)
