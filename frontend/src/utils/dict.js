import { getDictItems } from '@/api/system'

const _cache = {}

export async function getDictMap(type, useCache = true) {
  if (useCache && _cache[type]) return _cache[type]
  const res = await getDictItems(type, true)
  const map = {}
  ;(res.data || []).forEach(item => { map[item.code] = item.label })
  if (useCache) _cache[type] = map
  return map
}

export function buildDictLabel(typeCodes, map) {
  if (!typeCodes) return '-'
  return typeCodes.split(',').filter(Boolean).map(c => map[c] || c).join('、') || '-'
}
