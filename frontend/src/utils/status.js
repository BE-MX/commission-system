/** Domain dictionaries own labels and tones; unknown values remain visible. */
export function resolveStatus(value, dictionary = {}) {
  const entry = Object.hasOwn(dictionary, value) ? dictionary[value] : undefined
  if (entry !== undefined) {
    return typeof entry === 'string' ? { label: entry, type: 'info' }
      : { label: entry.label, type: entry.type || entry.tagType || entry.tag || entry.tone || 'info' }
  }
  return { label: value === null || value === undefined || value === '' ? '未提供' : `未知状态（${value}）`, type: 'info' }
}

export function statusDictionary(entries) {
  return Object.freeze(Object.fromEntries(entries.map(([value, label, type = 'info']) => [value, Object.freeze({ label, type })])))
}

/** Options and text-only histories derive from the same domain dictionary. */
export function statusLabels(dictionary) {
  return Object.freeze(Object.fromEntries(Object.entries(dictionary).map(([key, value]) => [key, value.label])))
}

export function statusTypes(dictionary) {
  return Object.freeze(Object.fromEntries(Object.entries(dictionary).map(([key, value]) => [key, value.type])))
}

export const ENABLED_STATUS = statusDictionary([
  [true, '启用', 'success'], [false, '停用', 'info'],
  [1, '启用', 'success'], [0, '停用', 'info'],
])
