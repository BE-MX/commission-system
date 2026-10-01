/** 与后端 CustomerRegister._normalise_phone 保持一致，供 kiosk 即时校验。 */
import { normalizeExpoPhone } from '../../../utils/validators.js'

export function normalisePhone(raw) {
  return normalizeExpoPhone(raw)
}
