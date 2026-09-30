/**
 * 我的提成明细：月度分组与汇总（纯函数，Node 可直接测试）。
 * 明细行按回款月份聚合成树表分组行，并支撑选中月份后的指标卡口径。
 */

/** 回款日期 → YYYY-MM；无日期的归入「未设置日期」 */
export function monthOf(value) {
  return value ? String(value).slice(0, 7) : '未设置日期'
}

/** 角色 → 明细行字段名前缀（salesperson_/supervisor_/second_supervisor_） */
export function roleField(role, suffix) {
  return {
    salesperson: `salesperson_${suffix}`,
    supervisor: `supervisor_${suffix}`,
    second_supervisor: `second_supervisor_${suffix}`,
  }[role]
}

/** 该角色在一行明细上的提成金额（数值） */
export function roleCommission(row, role) {
  return Number(row?.[roleField(role, 'commission')] || 0)
}

/** 该角色实际有提成的明细行数（提成为 0 的行不计入页签计数） */
export function visibleDetailCount(rows, role) {
  return (rows || []).filter(row => roleCommission(row, role) !== 0).length
}

/**
 * 明细行按月份分组为树表数据：月份分组行在前（按月升序），
 * 组内明细按回款日期、再按行 ID 升序；分组行合计回款/服务费/提成。
 */
export function groupedRows(rows, role) {
  const groups = new Map()
  ;(rows || []).filter(row => roleCommission(row, role) !== 0).forEach(row => {
    const month = monthOf(row.collection_date)
    if (!groups.has(month)) {
      groups.set(month, {
        id: `month-${month}`,
        isMonthGroup: true,
        month,
        total_payment_amount: 0,
        total_service_fee: 0,
        total_commission: 0,
        children: [],
      })
    }
    const group = groups.get(month)
    group.children.push(row)
    group.total_payment_amount += Number(row.payment_amount || 0)
    group.total_service_fee += Number(row.service_fee || 0)
    group.total_commission += roleCommission(row, role)
  })

  return Array.from(groups.values())
    .sort((a, b) => String(a.month).localeCompare(String(b.month)))
    .map(group => ({
      ...group,
      children: group.children.sort((a, b) => {
        const dateCompare = String(a.collection_date || '').localeCompare(String(b.collection_date || ''))
        return dateCompare || Number(a.id || 0) - Number(b.id || 0)
      }),
    }))
}

/**
 * 选中月份的指标卡口径：三种角色明细按回款月份过滤后分别合计，
 * 回款总额按明细行 ID 去重（同一笔回款可能在多个角色明细里各出现一次）。
 */
export function buildMonthSummary(detail, month) {
  const rowsById = new Map()
  const summary = {
    total_payment_amount: 0,
    total_salesperson_commission: 0,
    total_supervisor_commission: 0,
    total_second_supervisor_commission: 0,
    total_commission: 0,
  }

  ;(detail?.salesperson_details || []).filter(row => monthOf(row.collection_date) === month).forEach(row => {
    rowsById.set(row.id, row)
    summary.total_salesperson_commission += Number(row.salesperson_commission || 0)
  })
  ;(detail?.supervisor_details || []).filter(row => monthOf(row.collection_date) === month).forEach(row => {
    rowsById.set(row.id, row)
    summary.total_supervisor_commission += Number(row.supervisor_commission || 0)
  })
  ;(detail?.second_supervisor_details || []).filter(row => monthOf(row.collection_date) === month).forEach(row => {
    rowsById.set(row.id, row)
    summary.total_second_supervisor_commission += Number(row.second_supervisor_commission || 0)
  })

  rowsById.forEach(row => {
    summary.total_payment_amount += Number(row.payment_amount || 0)
  })
  summary.total_commission = summary.total_salesperson_commission
    + summary.total_supervisor_commission
    + summary.total_second_supervisor_commission
  return summary
}
