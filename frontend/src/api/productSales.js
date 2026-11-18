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
