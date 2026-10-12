export function stylistTotals(rows) {
  return {
    quantity: rows.reduce((sum, row) => sum + row.report_qty, 0),
    item_count: new Set(rows.map(row => row.item_id)).size,
    order_count: new Set(rows.map(row => row.order_id)).size,
    report_count: rows.length,
    active_days: new Set(rows.map(row => row.reported_at.slice(0, 10))).size,
  }
}

export function groupStylistFacts(rows, keyOf) {
  const groups = new Map()
  for (const row of rows) {
    const key = keyOf(row)
    if (!groups.has(key)) groups.set(key, [])
    groups.get(key).push(row)
  }
  return [...groups].map(([key, facts]) => ({
    key, label: key, ...stylistTotals(facts),
    evidence_refs: facts.map(row => ({ type: 'reports', id: row.id })),
  })).sort((a, b) => b.quantity - a.quantity || a.key.localeCompare(b.key))
}
