const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' })

export function tableSortParams({ prop, order }) {
  return prop && order ? { sort_field: prop, sort_order: order === 'ascending' ? 'asc' : 'desc' } : {}
}

export function isMissingSortValue(value) {
  return value == null || (typeof value === 'number' && Number.isNaN(value)) || value === '' || ['—', '-', '--'].includes(value)
}

export function getSortValue(row, field) {
  return String(field || '').split('.').reduce((value, key) => value?.[key], row)
}

/** Element Plus reverses the comparator for descending, including nulls. */
export function compareTableValues(left, right, order = 'ascending') {
  const leftMissing = isMissingSortValue(left)
  const rightMissing = isMissingSortValue(right)
  if (leftMissing || rightMissing) {
    const result = Number(leftMissing) - Number(rightMissing)
    return order === 'descending' ? -result : result
  }
  if (typeof left === 'number' && typeof right === 'number') return left - right
  if (typeof left === 'boolean' && typeof right === 'boolean') return Number(left) - Number(right)
  const numeric = /^[+-]?\d+(?:\.\d+)?$/
  if (numeric.test(String(left)) && numeric.test(String(right))) {
    const precision = Math.max(String(left).split('.')[1]?.length || 0, String(right).split('.')[1]?.length || 0)
    const scaled = value => {
      const [integer, fraction = ''] = String(value).split('.')
      return BigInt(integer + fraction.padEnd(precision, '0'))
    }
    const lvalue = scaled(left), rvalue = scaled(right)
    return lvalue > rvalue ? 1 : lvalue < rvalue ? -1 : 0
  }
  return collator.compare(String(left), String(right))
}

export function sortTableRows(rows, field, order, valueOf = row => getSortValue(row, field)) {
  if (!field || !order) return [...rows]
  const direction = order === 'descending' ? -1 : 1
  return rows.map((row, index) => ({ row, index })).sort((left, right) => {
    return direction * compareTableValues(valueOf(left.row), valueOf(right.row), order) || left.index - right.index
  }).map(item => item.row)
}

/** Sort every sibling list without moving children between parents or mutating the source. */
export function sortTableTree(rows, field, order, valueOf = row => getSortValue(row, field), childrenKey = 'children') {
  return sortTableRows(rows, field, order, valueOf).map(row => Array.isArray(row[childrenKey])
    ? { ...row, [childrenKey]: sortTableTree(row[childrenKey], field, order, valueOf, childrenKey) }
    : row)
}
