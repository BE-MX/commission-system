import { salesReturnClient as client } from './clients'

const unwrap = promise => promise.then(result => result.data ?? result)
const options = { showLoading: false, suppressToast: true }
export const listSalesReturns = (params, config = {}) => unwrap(client.get('', { ...options, ...config, params }))
export const getSalesReturn = id => unwrap(client.get(`/${id}`, options))
export const getReturnCustomers = (params, config = {}) => unwrap(client.get('/customers', { ...options, ...config, params }))
export const getReturnOrders = (params, config = {}) => unwrap(client.get('/orders', { ...options, ...config, params }))
export const getReturnOrderLines = id => unwrap(client.get(`/orders/${id}/lines`, options))
export const previewSalesReturn = body => unwrap(client.post('/preview', body, options))
export const createSalesReturn = body => unwrap(client.post('', body, options))
export const updateSalesReturn = (id, body) => unwrap(client.put(`/${id}`, body, options))
export const deleteSalesReturn = (id, version) => unwrap(client.delete(`/${id}`, { ...options, params: { version } }))
export const activateSalesReturn = (id, body) => unwrap(client.post(`/${id}/activate`, body, options))
export const reverseSalesReturn = (id, body) => unwrap(client.post(`/${id}/reverse`, body, options))
export const recordReturnCash = (id, body) => unwrap(client.post(`/${id}/cash`, body, options))
export const receiveSalesReturn = (id, body) => unwrap(client.post(`/${id}/receivings`, body, options))
export const inspectSalesReturn = (id, eventId, body) => unwrap(client.patch(`/${id}/receivings/${eventId}/inspection`, body, options))
export const stockSalesReturn = (id, eventId, body) => unwrap(client.post(`/${id}/receivings/${eventId}/stock`, body, options))
