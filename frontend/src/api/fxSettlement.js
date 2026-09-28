import { fxSettlementClient } from './clients'

const unwrap = promise => promise.then(result => result?.data ?? result)
export const getFxMarket = () => unwrap(fxSettlementClient.get('/market', { showLoading: false, suppressToast: true }))
export const calculateSettlement = data => unwrap(fxSettlementClient.post('/calculate', data, { showLoading: false, suppressToast: true }))
export const generateSettlementAdvice = data => unwrap(fxSettlementClient.post('/advice', data, { showLoading: false, suppressToast: true }))
