// The server uses ratios (0.5), while the existing UI uses percentages (50).
// Amounts, counts, percentage-point deltas and domain status values are never recalculated here.
export const unwrapPerfGoalResponse = value => value != null && Object.hasOwn(value, 'data') ? value.data : value
const percent = value => value == null ? null : Number.isFinite(Number(value)) ? Math.round(Number(value) * 1000000) / 10000 : null
const metricCell = cell => cell ? { ...cell, rate: percent(cell.rate), ...(Object.hasOwn(cell, 'prev_rate') ? { prev_rate: percent(cell.prev_rate) } : {}) } : cell
const metricCells = cells => Object.fromEntries(Object.entries(cells || {}).map(([key, cell]) => [key, metricCell(cell)]))
export const overviewPercentages = value => value ? { ...value, time_progress: percent(value.time_progress), metrics: metricCells(value.metrics), warnings: (value.warnings || []).map(warning => ({ ...warning, projected_rate: percent(warning.projected_rate) })) } : value
export const teamPercentages = value => value ? { ...value, rows: (value.rows || []).map(row => ({ ...row, overall_rate: percent(row.overall_rate), metrics: metricCells(row.metrics), members: (row.members || []).map(person => ({ ...person, gmv_rate: percent(person.gmv_rate) })) })) } : value
export const rankingPercentages = value => value ? { ...value, rows: (value.rows || []).map(row => Object.fromEntries(Object.entries(row).map(([key, cell]) => [key, ['gmv', 'new_sign', 'repeat_customers', 'repeat_amount'].includes(key) ? metricCell(cell) : cell]))) } : value
