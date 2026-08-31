const OUTCOME_CODE_PATTERN = /^[a-z][a-z0-9_]{0,31}$/


export function normalizeOutcomeAllocation(options, allocation, maxQty) {
  const outcomes = {}
  for (const option of options) {
    const value = allocation?.[option.code] ?? 0
    if (!Number.isInteger(value) || value < 0) {
      throw new Error('分流数量必须是大于等于 0 的整数')
    }
    outcomes[option.code] = value
  }

  const qty = Object.values(outcomes).reduce((sum, value) => sum + value, 0)
  if (qty < 1) throw new Error('至少分配 1 件')
  if (qty > maxQty) throw new Error(`分流数量合计不能超过 ${maxQty} 件`)
  return { qty, outcomes }
}


export function validateRouteRule(rule, routeSteps) {
  const triggerIndex = routeSteps.findIndex(step => step.process_id === rule.process_id)
  if (triggerIndex < 0) throw new Error('规则工序不在当前路线')

  if (rule.rule_type === 'required') return null
  if (rule.rule_type === 'optional') {
    if (rule.options?.length) throw new Error('非阻塞可选工序不能配置分流结果')
    return { process_id: rule.process_id, rule_type: 'optional', config: null }
  }
  if (rule.rule_type !== 'decision') throw new Error('不支持的规则类型')
  if (!Array.isArray(rule.options) || rule.options.length < 2) {
    throw new Error('分流判定至少需要两个结果')
  }

  const routeProcessIds = new Set(routeSteps.map(step => step.process_id))
  const codes = new Set()
  const options = rule.options.map(option => {
    const code = option.code?.trim()
    if (!OUTCOME_CODE_PATTERN.test(code || '')) {
      throw new Error('结果编码需要以小写字母开头，只能包含小写字母、数字和下划线')
    }
    if (codes.has(code)) throw new Error('结果编码不能重复')
    codes.add(code)

    const label = option.label?.trim()
    if (!label) throw new Error('结果名称不能为空')
    const targetIds = option.skip_process_ids
    if (!Array.isArray(targetIds)) throw new Error('请选择要跳过的后续工序')
    if (new Set(targetIds).size !== targetIds.length) throw new Error('同一结果不能重复选择跳过工序')
    for (const targetId of targetIds) {
      if (!routeProcessIds.has(targetId)) throw new Error('跳过目标不在当前路线')
      const targetIndex = routeSteps.findIndex(step => step.process_id === targetId)
      if (targetIndex <= triggerIndex) throw new Error('只能跳过当前工序之后的工序')
    }
    return { code, label, skip_process_ids: [...targetIds] }
  })

  return {
    process_id: rule.process_id,
    rule_type: 'decision',
    config: { options },
  }
}


export function buildConfirmedDomesticTemplate(routeSteps) {
  const processId = name => {
    const step = routeSteps.find(row => row.process_name === name)
    if (!step) throw new Error(`当前路线缺少“${name}”，不能应用头套网帽模板`)
    return step.process_id
  }

  const rules = [
    {
      process_id: processId('发加工点'),
      rule_type: 'decision',
      options: [
        { code: 'dandong', label: '丹东加工', skip_process_ids: [processId('李晓宏手钩'), processId('李晓宏递针')] },
        { code: 'lixiaohong', label: '李晓宏加工', skip_process_ids: [processId('丹东收货'), processId('丹东发货')] },
      ],
    },
    {
      process_id: processId('李晓宏手钩'),
      rule_type: 'decision',
      options: [
        { code: 'need_needle', label: '需要递针', skip_process_ids: [] },
        { code: 'no_needle', label: '无需递针', skip_process_ids: [processId('李晓宏递针')] },
      ],
    },
    {
      process_id: processId('毛坯质检'),
      rule_type: 'decision',
      options: [
        { code: 'qualified', label: '质检合格', skip_process_ids: [processId('毛坯维修')] },
        { code: 'repair', label: '需要维修', skip_process_ids: [] },
      ],
    },
    {
      process_id: processId('后处理定型'),
      rule_type: 'optional',
      options: [],
    },
  ]

  rules.forEach(rule => validateRouteRule(rule, routeSteps))
  return rules
}
