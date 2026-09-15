export const SHIPPING_STATION_PATH = '/shipping/scan'
export function isShippingStationPath(path) {
  return String(path || '').split(/[?#]/)[0].replace(/\/+$/, '') === SHIPPING_STATION_PATH
}
export const shippingStationLogin = () => ({ name: 'Login', query: { redirect: SHIPPING_STATION_PATH }, replace: true })
