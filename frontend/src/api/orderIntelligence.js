import { orderIntelligenceClient } from './clients'

const unwrap = promise => promise.then(res => (res && res.data !== undefined ? res.data : res))
const queryConfig = (params, config = {}) => ({ ...config, params, paramsSerializer: { indexes: null }, showLoading: false })

export const getOrderIntelligenceFilters = (params, config) => unwrap(
  orderIntelligenceClient.get('/filters', queryConfig(params, config)),
)
export const getOrderOverview = (params, config) => unwrap(
  orderIntelligenceClient.get('/overview', queryConfig(params, config)),
)
export const getCountryAnalysis = (params, config) => unwrap(
  orderIntelligenceClient.get('/countries', queryConfig(params, config)),
)
export const getPeopleAnalysis = (params, config) => unwrap(
  orderIntelligenceClient.get('/people', queryConfig(params, config)),
)
export const getCustomerProfileAnalysis = (params, config) => unwrap(
  orderIntelligenceClient.get('/customer-profiles', queryConfig(params, config)),
)
export const getCustomerActions = (params, config) => unwrap(
  orderIntelligenceClient.get('/customers', queryConfig(params, config)),
)
export const generateOrderAiBrief = data => unwrap(
  orderIntelligenceClient.post('/ai-brief', data, { showLoading: false }),
)
export const getActiveOrderAiBrief = () => unwrap(
  orderIntelligenceClient.get('/ai-brief/active', { showLoading: false }),
)
export const getLatestOrderAiBrief = () => unwrap(
  orderIntelligenceClient.get('/ai-brief/latest', { showLoading: false }),
)
export const getOrderAiBriefStatus = jobId => unwrap(
  orderIntelligenceClient.get(`/ai-brief/${jobId}`, { showLoading: false }),
)
