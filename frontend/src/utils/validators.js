/**
 * 基础校验只返回布尔值，不包含业务错误文案，也不替代服务端校验。
 *
 * 手机策略必须按业务选择：mainland-mobile 限 1[3-9] 开头的 11 位；
 * international 接受常见 + / 空格 / 括号 / 横杠且有 7–15 位数字；
 * expo-digits 复用 kiosk 的 NFKC、去非数字、可去 86、11 位规则，
 * 不能把它用于 WhatsApp、TEL/Fax 或国际号码的自动归一。
 *
 * isEmail 是基础地址形状检查，不能验证邮箱存在或投递能力。
 * 原本只有必填校验的页面，不应因采用工具而增加邮箱格式限制。
 *
 * isAmount 默认检查无符号十进制、最多两位小数、大于零；
 * precision / maxIntegerDigits / allowZero / allowNegative 必须由业务决定。
 * format: 'number' 仅检查有限数值与正负范围，保留数字控件的既有精度，
 * 不把四位单价或数量强行限制成两位小数。
 * 金额分配、舍入、余额比较、BigInt/cents 解析继续由领域函数负责。
 */

function inputText(value, trim = true) {
  if (typeof value !== 'string' && typeof value !== 'number') return ''
  const text = String(value)
  return trim ? text.trim() : text
}

export function normalizeExpoPhone(value) {
  const digits = inputText(value).normalize('NFKC').replace(/\D/g, '')
  const local = digits.length === 13 && digits.startsWith('86') ? digits.slice(2) : digits
  return local.length === 11 ? local : ''
}

export function isPhone(value, { strategy = 'mainland-mobile', allowEmpty = false } = {}) {
  const text = inputText(value)
  if (!text) return allowEmpty
  if (strategy === 'expo-digits') return Boolean(normalizeExpoPhone(text))
  if (strategy === 'mainland-mobile') return /^1[3-9]\d{9}$/.test(text)
  if (strategy === 'international') {
    const digits = text.replace(/\D/g, '')
    return /^\+?[\d ()-]+$/.test(text) && digits.length >= 7 && digits.length <= 15
  }
  return false
}

export function isEmail(value, { allowEmpty = false } = {}) {
  const text = inputText(value)
  return text ? /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(text) : allowEmpty
}

export function isAmount(value, {
  format = 'decimal', precision = 2, maxIntegerDigits = null,
  allowZero = false, allowNegative = false, allowEmpty = false, trim = true,
} = {}) {
  const text = inputText(value, trim)
  if (!text) return allowEmpty
  const number = Number(text)
  if (!Number.isFinite(number) || (!allowNegative && number < 0) || (!allowZero && number === 0)) return false
  if (format === 'number') return true
  if (format !== 'decimal') return false
  const match = /^(-?)(\d+)(?:\.(\d+))?$/.exec(text)
  if (!match || (match[1] && !allowNegative)) return false
  if (precision !== null && (!Number.isInteger(precision) || precision < 0 || (match[3]?.length || 0) > precision)) return false
  if (maxIntegerDigits !== null && (!Number.isInteger(maxIntegerDigits) || maxIntegerDigits < 1 || match[2].length > maxIntegerDigits)) return false
  return true
}
