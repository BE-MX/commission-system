export const FX_APP_PATH = '/fx-settlement'
export const FX_DESKTOP_PATH = '/invoice/fx-settlement'

export function isFxSettlementPath(path) {
  const pathname = String(path || '').split(/[?#]/)[0].replace(/\/+$/, '')
  return pathname === FX_APP_PATH || pathname === FX_DESKTOP_PATH
}

export const fxSettlementLogin = () => ({ name: 'Login', query: { redirect: FX_APP_PATH }, replace: true })
