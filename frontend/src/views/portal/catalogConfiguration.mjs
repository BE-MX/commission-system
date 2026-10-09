export const catalogStates = { draft: '草稿', published: '已发布', disabled: '已下架' }
export function catalogConfiguration(form) {
  const body = {}
  for (const key of ['display_name', 'color_name', 'inventory_unit', 'sale_unit']) {
    const value = form[key].trim(), limit = key.endsWith('unit') ? 32 : 128
    if (!value || value.length > limit || /[<>\p{C}]/u.test(value)) throw new Error('请填写有效的型号、颜色及库存/销售单位，使用纯文本。')
    body[key] = value
  }
  for (const key of ['conversion_factor', 'safety_buffer']) {
    const value = form[key].trim()
    if (!/^(0|[1-9][0-9]{0,7})(\.[0-9]{1,6})?$/.test(value) || (key === 'conversion_factor' && Number(value) <= 0)) throw new Error('换算系数必须大于零，安全余量不能为负；最多 8 位整数和 6 位小数。')
    body[key] = value
  }
  for (const key of ['min_qty', 'step_qty']) {
    if (!Number.isInteger(form[key]) || form[key] < 1 || form[key] > 10000) throw new Error('起订量和步长须为 1–10000 的整数。')
    body[key] = form[key]
  }
  if (body.min_qty % body.step_qty) throw new Error('起订量须为下单步长的整数倍。')
  body.reason = form.reason.trim()
  if (!body.reason || body.reason.length > 500) throw new Error('请填写 1–500 字的操作原因。')
  return body
}
export function sourceIdentity(form) {
  for (const key of ['product_id', 'sku_id']) if (!/^[1-9][0-9]{0,18}$/.test(form[key]) || BigInt(form[key]) > 9223372036854775807n) throw new Error('请选择规范的方舟产品 ID 和 SKU ID，不可包含前导零。')
  if (!['hair', 'accessory'].includes(form.product_kind)) throw new Error('请选择商品类别。')
  return { product_id: form.product_id, sku_id: form.sku_id, product_kind: form.product_kind }
}
