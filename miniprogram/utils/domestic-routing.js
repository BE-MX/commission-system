function optionCodes(options) {
  return (options || []).map(function (option) { return option.code })
}

function buildDecisionSubmission(options, values, maxQty, reportMode) {
  var codes = optionCodes(options)
  values = values || {}
  if (!codes.length) throw new Error('当前工序没有可选结果')

  if (reportMode === 'unit') {
    var selected = codes.filter(function (code) { return values[code] === true || values[code] === 1 })
    var unknownSelected = Object.keys(values).filter(function (code) {
      return codes.indexOf(code) < 0 && (values[code] === true || values[code] === 1)
    })
    if (selected.length !== 1 || unknownSelected.length) throw new Error('请选择一个处理结果')
    var unitOutcomes = {}
    unitOutcomes[selected[0]] = 1
    return { qty: 1, outcomes: unitOutcomes }
  }

  var outcomes = {}
  var total = 0
  for (var i = 0; i < codes.length; i++) {
    var code = codes[i]
    var raw = values[code]
    var qty = raw === '' || raw === undefined || raw === null ? 0 : Number(raw)
    if (!Number.isInteger(qty) || qty < 0) throw new Error('分配数量必须是非负整数')
    outcomes[code] = qty
    total += qty
  }
  if (total < 1) throw new Error('至少一个结果需要分配数量')
  if (total > maxQty) throw new Error('分配总数不能超过可报数量')
  return { qty: total, outcomes: outcomes }
}

function decorateProgress(step) {
  var completed = Number(step.completed_qty || 0)
  var skipped = Number(step.skipped_qty || 0)
  var passed = Number(step.passed_qty || 0)
  var orderQty = Number(step.order_qty || 0)
  return {
    completedQty: completed,
    skippedQty: skipped,
    passedQty: passed,
    percent: orderQty ? Math.min(100, Math.round(passed / orderQty * 100)) : 0,
    done: orderQty > 0 && passed >= orderQty
  }
}

function publicStep(step) {
  var result = {
    completed_qty: Number(step.completed_qty || 0),
    skipped_qty: Number(step.skipped_qty || 0),
    passed_qty: Number(step.passed_qty || 0),
    order_qty: Number(step.order_qty || 0),
    reportable_qty: Number(step.reportable_qty || 0),
    step_order: Number(step.step_order || 0),
    process_name: String(step.process_name || '')
  }
  if (result.skipped_qty > 0) result.skip_label = '无需此工序'
  return result
}

module.exports = {
  buildDecisionSubmission: buildDecisionSubmission,
  decorateProgress: decorateProgress,
  publicStep: publicStep
}
