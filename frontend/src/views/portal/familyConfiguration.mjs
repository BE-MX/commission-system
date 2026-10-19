export const gradeLabels = { standard: 'Standard Double Drawn', super: 'Super Double Drawn', ultra: 'Ultra Double Drawn' }
export const colorTypeLabels = { solid: '纯色 Solid', piano: '钢琴色 Piano', ombre: '渐变 Ombre', balayage: '巴黎画染 Balayage' }
export const colorTypeSources = { exact: '色型表', inferred: '按色号推断', missing: '未识别' }
const DECIMAL = /^(0|[1-9][0-9]{0,7})(\.[0-9]{1,6})?$/
const PLAIN = /[<>\p{C}]/u

function reasonOf(form) {
  const reason = form.reason.trim()
  if (!reason || reason.length > 500) throw new Error('请填写 1–500 字的操作原因。')
  return reason
}

export function familyBody(form) {
  const display_name = form.display_name.trim()
  if (!display_name || display_name.length > 128 || PLAIN.test(display_name)) throw new Error('请填写纯文本产品族名称（≤128 字）。')
  for (const key of ['unit_weight_grams', 'out_of_stock_below']) {
    if (!DECIMAL.test(form[key].trim())) throw new Error('单位克重与无货阈值须为非负小数，最多 8 位整数和 6 位小数。')
  }
  if (Number(form.unit_weight_grams) <= 0) throw new Error('单位克重必须大于零。')
  for (const key of ['min_qty', 'step_qty']) {
    if (!Number.isInteger(form[key]) || form[key] < 1 || form[key] > 10000) throw new Error('起订量和步长须为 1–10000 的整数。')
  }
  if (form.min_qty % form.step_qty) throw new Error('起订量须为步长的整数倍。')
  const allowed_grades = Object.keys(gradeLabels).filter(grade => form.allowed_grades.includes(grade))
  if (!allowed_grades.length) throw new Error('至少展示一个工艺档。')
  if (!Number.isInteger(form.sort_order) || form.sort_order < 0 || form.sort_order > 9999) throw new Error('排序须为 0–9999 的整数。')
  if (!['enabled', 'disabled'].includes(form.status)) throw new Error('请选择产品族状态。')
  return { display_name, unit_weight_grams: form.unit_weight_grams.trim(), min_qty: form.min_qty, step_qty: form.step_qty,
    out_of_stock_below: form.out_of_stock_below.trim(), allowed_grades, sort_order: form.sort_order, status: form.status, reason: reasonOf(form) }
}

export function assignBody(form) {
  const item_ids = [...new Set(form.item_ids)]
  if (!item_ids.length || item_ids.length > 200) throw new Error('请勾选 1–200 个商品。')
  if (form.clear) return { item_ids, family_code: null, grade: null, reason: reasonOf(form) }
  if (!/^[a-z0-9_]{1,32}$/.test(form.family_code || '')) throw new Error('请选择产品族。')
  if (!gradeLabels[form.grade]) throw new Error('请选择工艺档。')
  return { item_ids, family_code: form.family_code, grade: form.grade, reason: reasonOf(form) }
}

export function swatchBody(form) {
  const color_code = form.color_code.trim(), display_name = form.display_name.trim()
  if (!color_code || color_code.length > 64 || PLAIN.test(color_code)) throw new Error('请填写纯文本色号（≤64 字）。')
  if (display_name.length > 128 || PLAIN.test(display_name)) throw new Error('颜色展示名须为纯文本（≤128 字）。')
  if (!['enabled', 'disabled'].includes(form.status)) throw new Error('请选择色块状态。')
  const body = { color_code, display_name: display_name || null, status: form.status, reason: reasonOf(form) }
  if (form.image === 'keep') return { ...body, asset_id: null, keep_image: true }
  if (form.image === 'remove') return { ...body, asset_id: null, keep_image: false }
  if (!form.asset_id || !form.asset_reference?.startsWith(form.asset_id + ':')) throw new Error('请先选择并预览要绑定的色块图。')
  return { ...body, asset_id: form.asset_id, asset_reference: form.asset_reference, keep_image: false }
}

export function packHint(family) {
  const weight = Number(family.unit_weight_grams) * family.step_qty
  return `每步 ${family.step_qty} ${family.sale_unit} ≈ ${Number.isFinite(weight) ? +weight.toFixed(2) : '-'} g`
}
