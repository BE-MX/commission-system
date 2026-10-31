import { commerceMigrationClient as api } from './clients'

const paths = { catalog: '', inventory: '/inventory', orders: '/orders', finance: '/finance',
  fulfillment: '/fulfillment', production: '/production', materials: '/materials', pendingMaterials: '/materials/pending', legacy_settlement: '/settlement' }
function prefix(kind) {
  if (!Object.hasOwn(paths, kind)) throw new Error('未知承接清单类型')
  return paths[kind]
}
export const previewMigration = (kind, body, config = {}) => api.post(`${prefix(kind)}/preview`, body, config)
export const applyMigration = (kind, body, config = {}) => api.post(`${prefix(kind)}${kind === 'legacy_settlement' ? '' : '/batches'}`, body, config)
export const getMigrationRecords = (params, config = {}) => api.get('/records/page', { ...config, params })
export const getMigrationRecord = (id, config = {}) => api.get(`/records/${id}`, config)
export const prepareMigrationActivation = (body, config = {}) => api.post('/activation/prepare', body, config)
export const activateMigration = (body, config = {}) => api.post('/activation', body, config)
