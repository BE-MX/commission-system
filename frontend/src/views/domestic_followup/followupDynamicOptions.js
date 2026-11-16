export function dictOptionLabels(rows) {
  return (rows || []).map(row => typeof row === 'string' ? row : row?.label).filter(Boolean)
}
