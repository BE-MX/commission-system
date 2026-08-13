import { orderIntelligenceClient } from './clients'

const unwrap = promise => promise.then(res => (res && res.data !== undefined ? res.data : res))
const queryConfig = params => ({ params, paramsSerializer: { indexes: null }, showLoading: false })

export const getOrderIntelligenceFilters = params => unwrap(
  orderIntelligenceClient.get('/filters', queryConfig(params)),
)
export const getOrderOverview = params => unwrap(
  orderIntelligenceClient.get('/overview', queryConfig(params)),
)
export const getCountryAnalysis = params => unwrap(
  orderIntelligenceClient.get('/countries', queryConfig(params)),
)
export const getPeopleAnalysis = params => unwrap(
  orderIntelligenceClient.get('/people', queryConfig(params)),
)
export const getCustomerProfileAnalysis = params => unwrap(
  orderIntelligenceClient.get('/customer-profiles', queryConfig(params)),
)
export const getCustomerActions = params => unwrap(
  orderIntelligenceClient.get('/customers', queryConfig(params)),
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
