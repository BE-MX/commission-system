import { shipmentClient as request } from './clients'
const unwrap = promise => promise.then(res => res.data ?? res)
export const getShipmentCapabilities = () => unwrap(request.get('/shipments/capabilities', { showLoading: false }))
export const quoteShipment = (id, body) => unwrap(request.post(`/invoices/${id}/shipment-quotes`, body, { showLoading: false }))
export const createShipment = (id, body) => unwrap(request.post(`/invoices/${id}/shipment-settlements`, body))
export const listShipments = id => unwrap(request.get(`/shipments/order/${id}`, { showLoading: false }))
export const getShipment = id => unwrap(request.get(`/shipments/${id}`, { showLoading: false }))
export const changeShipment = (id, action, body) => unwrap(request.post(`/shipments/${id}/${action}`, body))
