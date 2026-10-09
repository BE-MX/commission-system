import { shipmentClient as request } from './clients'
const unwrap = promise => promise.then(res => res.data ?? res)
export const getShipmentCapabilities = () => unwrap(request.get('/shipments/capabilities', { showLoading: false }))
export const quoteShipment = (id, body) => unwrap(request.post(`/invoices/${id}/shipment-quotes`, body, { showLoading: false }))
const shipmentRecoveryOptions = { showLoading: false, suppressToast: true, redirectOnUnauthorized: false }
export const createShipment = (id, body, signal) => unwrap(request.post(`/invoices/${id}/shipment-settlements`, body, { ...shipmentRecoveryOptions, signal }))
export const inspectShipmentSubmission = (id, body, signal) => unwrap(request.post(`/invoices/${id}/shipment-settlements/submission-status`, body, { ...shipmentRecoveryOptions, signal }))
export const listShipments = id => unwrap(request.get(`/shipments/order/${id}`, { showLoading: false }))
export const getShipment = id => unwrap(request.get(`/shipments/${id}`, { showLoading: false }))
export const changeShipment = (id, action, body) => unwrap(request.post(`/shipments/${id}/${action}`, body))
export const confirmShipmentOutbound = (id, body) => unwrap(request.post(`/shipments/${id}/confirm-outbound`, body, shipmentRecoveryOptions))
export const reconcileShipmentTarget = (id, kind, body) => unwrap(request.post(`/shipments/${id}/reconcile-${kind}`, body, shipmentRecoveryOptions))
export const retryShipmentTarget = (id, kind, body) => unwrap(request.post(`/shipments/${id}/retry-${kind}`, body))
