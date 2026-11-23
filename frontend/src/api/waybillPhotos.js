import { shipmentClient, shippingClient } from './clients'

export function listWaybillPhotos({ inspectionId, shipmentId }, config) {
  return shipmentId
    ? shipmentClient.get(`/tracking/shipments/${shipmentId}/waybill-photos`, config)
    : shippingClient.get(`/records/${inspectionId}/waybill-photos`, config)
}

export function loadWaybillPhoto(photo, variant, signal) {
  return shippingClient.get(`/records/${photo.inspection_id}/waybill-photos/${photo.id}`, {
    params: { variant }, signal, responseType: 'blob', suppressToast: true, showLoading: false,
  })
}
