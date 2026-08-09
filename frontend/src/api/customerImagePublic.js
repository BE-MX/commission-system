import { customerImagePublicClient } from './clients'

const SILENT_REQUEST = { showLoading: false, suppressToast: true }

export function getContext() {
  return customerImagePublicClient.get('/context', { ...SILENT_REQUEST })
}

export function listProducts() {
  return customerImagePublicClient.get('/products', { ...SILENT_REQUEST })
}

export function uploadLogo(file) {
  const form = new FormData()
  form.append('file', file)
  return customerImagePublicClient.post('/logo', form, { ...SILENT_REQUEST })
}

export function getProductAssetBlob(productId, assetId) {
  return customerImagePublicClient.get(
    `/products/${productId}/assets/${assetId}/content`,
    { ...SILENT_REQUEST, responseType: 'blob' },
  )
}

export function getAssetBlob(assetId) {
  return customerImagePublicClient.get(`/assets/${assetId}/content`, {
    ...SILENT_REQUEST,
    responseType: 'blob',
  })
}

export function createGeneration(data) {
  return customerImagePublicClient.post('/generations', data, { ...SILENT_REQUEST })
}

export function listGenerations() {
  return customerImagePublicClient.get('/generations', { ...SILENT_REQUEST })
}

export function getGeneration(generationId) {
  return customerImagePublicClient.get(
    `/generations/${generationId}`,
    { ...SILENT_REQUEST },
  )
}
