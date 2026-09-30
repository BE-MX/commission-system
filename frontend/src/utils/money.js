/**
 * 统一金额格式化（DESIGN.md「Format Spec」）。
 * 列表默认两位小数 + 千分位；单价等精度场景传 precision=4。
 * 收敛路径同 utils/datetime.js：新代码禁止散写 toFixed / toLocaleString / Intl.NumberFormat。
 */
const formatters = new Map()

function formatter(precision) {
  if (!formatters.has(precision)) {
    formatters.set(precision, new Intl.NumberFormat('en-US', {
      minimumFractionDigits: precision,
      maximumFractionDigits: precision,
    }))
  }
  return formatters.get(precision)
}

export function formatMoney(value, precision = 2) {
  const number = Number(value)
  return formatter(precision).format(Number.isFinite(number) ? number : 0)
}
