import { customerImageClient } from './clients'

const SILENT_REQUEST = { showLoading: false, suppressToast: true }

export function searchCustomers(params = {}) {
  return customerImageClient.get('/customers', { params, showLoading: false })
}

export function listProducts(params = {}) {
  return customerImageClient.get('/products', { params, showLoading: false })
}

export function createProduct(data) {
  return customerImageClient.post('/products', data, { ...SILENT_REQUEST })
}

export function updateProduct(productId, data) {
  return customerImageClient.put(`/products/${productId}`, data, { ...SILENT_REQUEST })
}

export function deleteProduct(productId) {
  return customerImageClient.delete(`/products/${productId}`, { ...SILENT_REQUEST })
}

export function publishProduct(productId) {
  return customerImageClient.post(`/products/${productId}/publish`, {}, { ...SILENT_REQUEST })
}

export function unpublishProduct(productId) {
  return customerImageClient.post(`/products/${productId}/unpublish`, {}, { ...SILENT_REQUEST })
}

export function listInvites(params = {}) {
  return customerImageClient.get('/invites', { params, showLoading: false })
}

export function createInvite(data) {
  return customerImageClient.post('/invites', data, { ...SILENT_REQUEST })
}

export function revokeInvite(inviteId) {
  return customerImageClient.post(`/invites/${inviteId}/revoke`, {}, { ...SILENT_REQUEST })
}

export function listGenerations(params = {}) {
  return customerImageClient.get('/generations', { params, showLoading: false })
}
