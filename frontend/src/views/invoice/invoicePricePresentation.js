export const COLOR_TYPE_TEXT = { solid: '纯色 Solid', piano: '钢琴色 Piano', ombre: '渐变 Ombre', balayage: '巴黎画染 Balayage' }

export const stdColumnDefs = [
  { key: 'series', label: '系列 + 工艺档' }, { key: 'length', label: '长度' },
  { key: 'weight', label: '克重' }, { key: 'color-type', label: '色型' },
  { key: 'price', label: '标准价' }, { key: 'updated', label: '更新时间' },
]
export const colorColumnDefs = [{ key: 'code', label: '色号' }, { key: 'type', label: '色型' }]
export const ruleColumnDefs = [
  { key: 'customer', label: '客户' }, { key: 'customer-id', label: '客户 ID' },
  { key: 'adjust', label: '调价方式' }, { key: 'enabled', label: '启用' },
  { key: 'remark', label: '备注' },
]
export const customColumnDefs = [
  { key: 'name', label: '产品名' }, { key: 'model', label: 'Model' },
  { key: 'color', label: 'Color' }, { key: 'size', label: 'Length' },
  { key: 'unit', label: 'Unit' }, { key: 'count', label: '使用次数' },
  { key: 'okki', label: 'OKKI 关联' },
]

export function emptyStd() {
  return { id: null, series_grade: '', length: '', weight_unit: '', color_type: 'solid', price: null, currency: 'USD' }
}

export function emptyRule() {
  return { id: null, customer_id: '', customer_name: '', adjust_type: 'fixed', adjust_value: 0, enabled: true, remark: '' }
}

export function colorTypeText(key) {
  return COLOR_TYPE_TEXT[key] || key
}

export function ruleText(row) {
  const sign = Number(row.adjust_value) >= 0 ? '+' : ''
  return row.adjust_type === 'percent'
    ? `标准价 ${sign}${Number(row.adjust_value)}%`
    : `标准价 ${sign}${Number(row.adjust_value)}（固定额）`
}
