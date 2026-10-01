/**
 * 统一金额格式化（DESIGN.md「Format Spec」）。
 * 列表默认两位小数 + 千分位；单价等精度场景传 precision=4。
 * 收敛路径同 utils/datetime.js：新代码禁止散写 toFixed / toLocaleString / Intl.NumberFormat。
 */
const formatters = new Map()

function formatter({ precision, minimumPrecision, notation, currency, currencyDisplay, locale }) {
  const key = JSON.stringify([precision, minimumPrecision, notation, currency, currencyDisplay, locale])
  if (!formatters.has(key)) {
    formatters.set(key, new Intl.NumberFormat(locale, {
      minimumFractionDigits: minimumPrecision, maximumFractionDigits: precision, notation,
      ...(currency ? { style: 'currency', currency, currencyDisplay } : {}),
    }))
  }
  return formatters.get(key)
}

/** Display only; never use grouped strings for calculations or API payloads. */
export function formatMoney(value, precisionOrOptions = 2) {
  const options = typeof precisionOrOptions === 'number' ? { precision: precisionOrOptions } : precisionOrOptions || {}
  const precision = Number.isInteger(options.precision) && options.precision >= 0 && options.precision <= 20 ? options.precision : 2
  const missing = options.missing ?? 0
  const notation = options.notation === 'compact' ? 'compact' : 'standard'
  const minimumPrecision = notation === 'compact' ? 0 : precision
  const absent = value == null || value === '' || !Number.isFinite(Number(value))
  if (absent && typeof missing === 'string') return missing
  const number = Number(value)
  return formatter({ precision, minimumPrecision, notation, currency: options.currency, currencyDisplay: options.currencyDisplay || 'code', locale: options.locale || 'en-US' })
    .format(absent ? missing : number)
}
