// Pure helpers for the family detail selector. No DOM, no network.
export const COLOR_TYPE_LABELS = { solid: 'Solid', piano: 'Piano', ombre: 'Ombre', balayage: 'Balayage' }
const COLOR_TYPE_ORDER = ['solid', 'piano', 'ombre', 'balayage']
const available = variant => variant.availability === 'available' && variant.unit_price != null

function unique(values) { return [...new Set(values)] }

export function gradeOptions(variants) {
  return unique(variants.map(v => v.grade)).map(grade => {
    const members = variants.filter(v => v.grade === grade)
    return { value: grade, label: members[0].grade_label, available: members.some(available) }
  })
}

export function lengthOptions(variants, grade) {
  const members = variants.filter(v => v.grade === grade)
  return unique(members.map(v => v.length)).map(length => ({ value: length,
    available: members.some(v => v.length === length && available(v)) }))
}

/** Colors for one grade + length, grouped by color type in business order. */
export function colorGroups(variants, grade, length) {
  const members = variants.filter(v => v.grade === grade && v.length === length)
  const groups = new Map()
  for (const variant of members) {
    const type = COLOR_TYPE_ORDER.includes(variant.color_type) ? variant.color_type : 'other'
    if (!groups.has(type)) groups.set(type, [])
    if (!groups.get(type).some(v => v.color_key === variant.color_key)) groups.get(type).push(variant)
  }
  return [...COLOR_TYPE_ORDER, 'other'].filter(type => groups.has(type))
    .map(type => ({ type, label: COLOR_TYPE_LABELS[type] || 'Other shades', colors: groups.get(type) }))
}

/** Keep the customer's choices when still valid; otherwise fall back to the first available option. */
export function resolveSelection(variants, wanted = {}) {
  if (!variants.length) return { grade: null, length: null, colorKey: null, variant: null }
  const pick = (options, value) => options.find(o => o.value === value)?.value
    ?? options.find(o => o.available)?.value ?? options[0].value
  const grade = pick(gradeOptions(variants), wanted.grade)
  const length = pick(lengthOptions(variants, grade), wanted.length)
  const colors = colorGroups(variants, grade, length).flatMap(group => group.colors)
  const variant = colors.find(v => v.color_key === wanted.colorKey) ?? colors.find(available) ?? colors[0]
  return { grade, length, colorKey: variant.color_key, variant }
}

/** Poll results only touch stock fields of variants that are still in the current detail. */
export function mergeAvailability(variants, items) {
  const latest = new Map((items || []).map(item => [item.item_id, item]))
  return variants.map(v => latest.has(v.item_id) ? { ...v, availability: latest.get(v.item_id).availability,
    stock_display: latest.get(v.item_id).stock_display, inventory_observed_at: latest.get(v.item_id).inventory_observed_at } : v)
}

export function stockLabel(variant) {
  if (variant.availability === 'available') return variant.stock_display ? `${variant.stock_display} in stock` : 'In stock'
  if (variant.availability === 'unavailable') return 'Out of stock'
  return 'Availability pending'
}

/** Move one step from the nearest valid quantity; results stay on min + k*step within 10,000. */
export function stepQuantity(current, step, minimum, direction) {
  const value = Number(current), ceiling = minimum + Math.floor((10000 - minimum) / step) * step
  const aligned = Number.isSafeInteger(value) && value >= minimum
    ? minimum + Math.floor((Math.min(value, ceiling) - minimum) / step) * step : minimum
  return Math.min(ceiling, Math.max(minimum, aligned + direction * step))
}

export function gramsFor(line) {
  const weight = Number(line.unit_weight_grams), quantity = Number(line.quantity)
  return Number.isFinite(weight) && weight > 0 && Number.isSafeInteger(quantity) ? weight * quantity : null
}

export function formatGrams(value) {
  if (value == null) return '—'
  return value >= 1000 ? `${+(value / 1000).toFixed(2)} kg` : `${+value.toFixed(1)} g`
}

/** Sum only lines with a known weight; report whether any line was unknown. */
export function selectionWeight(lines) {
  let total = 0, complete = true
  for (const line of lines) {
    const grams = gramsFor(line)
    if (grams == null) complete = false
    else total += grams
  }
  return { grams: total, complete }
}
