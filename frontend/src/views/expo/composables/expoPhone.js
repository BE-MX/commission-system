/** 与后端 CustomerRegister._normalise_phone 保持一致，供 kiosk 即时校验。 */
export function normalisePhone(raw) {
  const digits = (raw || '').normalize('NFKC').replace(/\D/g, '')
  const local = digits.length === 13 && digits.startsWith('86') ? digits.slice(2) : digits
  return local.length === 11 ? local : ''
}
