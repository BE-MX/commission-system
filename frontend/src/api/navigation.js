import { systemClient } from './clients'

const quiet = { showLoading: false, suppressToast: true }

export function getNavigationPreferences(config = {}) {
  return systemClient.get('/navigation-preferences', { ...quiet, ...config })
}

export function saveNavigationPreferences(items, config = {}) {
  return systemClient.put('/navigation-preferences', { items }, { ...quiet, ...config })
}
