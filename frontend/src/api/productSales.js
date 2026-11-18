import { productSalesClient } from './clients'

const unwrap = promise => promise.then(res => (res && res.data !== undefined ? res.data : res))

export const listNameMappings = (params, config = {}) => unwrap(
  productSalesClient.get('/mappings', { ...config, params, showLoading: false }),
)
export const refreshNameMappings = () => unwrap(productSalesClient.post('/mappings/refresh'))
export const saveNameMappings = items => unwrap(productSalesClient.put('/mappings', { items }))
export const listCurrentModels = (config = {}) => unwrap(
  productSalesClient.get('/models', { ...config, showLoading: false }),
)
export const getSalesCoverage = (params, config = {}) => unwrap(
  productSalesClient.get('/coverage', { ...config, params, showLoading: false }),
)

const query = (params, config = {}) => ({ ...config, params, paramsSerializer: { indexes: null }, showLoading: false })
export const getRadar = (params, config) => unwrap(productSalesClient.get('/radar', query(params, config)))
export const getRadarItem = (params, config) => unwrap(productSalesClient.get('/radar/item', query(params, config)))
export const getRadarScopes = (params, config) => unwrap(productSalesClient.get('/radar/scopes', query(params, config)))
export const explainRadarItem = payload => unwrap(productSalesClient.post('/radar/insight', payload, { showLoading: false }))
