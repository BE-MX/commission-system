import { devlogClient as client } from './clients'
const quiet = { showLoading: false, suppressToast: true }
const clean = params => Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v != null))
export const devlogApi = {
  summary: (params, config) => client.get('/summary', { ...quiet, ...config, params: clean(params) }),
  item: (id, config) => client.get(`/items/${id}`, { ...quiet, ...config }),
  pending: config => client.get('/pending', { ...quiet, ...config }),
  health: config => client.get('/health', { ...quiet, ...config }),
}
