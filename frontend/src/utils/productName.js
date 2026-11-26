// 发制品产品名按「系列/长度/颜色/克重」拼接，颜色本身可能含斜杠（如 #P8/24）。
// 拆出颜色等关键规格，让界面先展示用户真正要辨认的部分；不符合该格式时整体当作系列名。
const LENGTH = /^\d+(\.\d+)?$/
const WEIGHT = /^\d+(\.\d+)?g$/i

export function parseProductName(name) {
  const raw = String(name || '').trim()
  const parts = raw.split('/').map(part => part.trim())
  if (parts.length >= 4 && LENGTH.test(parts[1]) && WEIGHT.test(parts.at(-1))) {
    return {
      raw,
      series: parts[0],
      length: parts[1],
      color: parts.slice(2, -1).join('/'),
      weight: parts.at(-1),
    }
  }
  return { raw, series: raw, length: '', color: '', weight: '' }
}
