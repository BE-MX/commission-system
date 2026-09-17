export const SHIPPING_STATION_PATH = '/shipping/scan'
export function isShippingStationPath(path) {
  return String(path || '').split(/[?#]/)[0].replace(/\/+$/, '') === SHIPPING_STATION_PATH
}
export const shippingStationLogin = () => ({ name: 'Login', query: { redirect: SHIPPING_STATION_PATH }, replace: true })

// Inspection notifications stay in the main site's login flow on mobile, preserving id/version.
export function isShippingInspectionPath(path) {
  return String(path || '').split(/[?#]/)[0].replace(/\/+$/, '') === '/shipping/inspections'
}
