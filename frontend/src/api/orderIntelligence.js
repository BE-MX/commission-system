import { orderIntelligenceClient } from './clients'

const unwrap = promise => promise.then(res => (res && res.data !== undefined ? res.data : res))

export const getOrderIntelligenceFilters = params => unwrap(
  orderIntelligenceClient.get('/filters', { params, showLoading: false }),
)
export const getOrderOverview = params => unwrap(
  orderIntelligenceClient.get('/overview', { params, showLoading: false }),
)
export const getCountryAnalysis = params => unwrap(
  orderIntelligenceClient.get('/countries', { params, showLoading: false }),
)
export const getPeopleAnalysis = params => unwrap(
  orderIntelligenceClient.get('/people', { params, showLoading: false }),
)
export const getCustomerActions = params => unwrap(
  orderIntelligenceClient.get('/customers', { params, showLoading: false }),
)
export const generateOrderAiBrief = data => unwrap(
  orderIntelligenceClient.post('/ai-brief', data, { showLoading: false }),
)
