export async function saveStepsThenRules({ saveSteps, saveRules, reload }) {
  await saveSteps()

  if (!saveRules) {
    await reload({ partial: false })
    return { status: 'steps_saved' }
  }

  try {
    await saveRules()
  } catch (error) {
    await reload({ partial: true, error })
    return { status: 'partial', error }
  }

  await reload({ partial: false })
  return { status: 'saved' }
}


export function mergeRouteSteps(steps, rules, drafts = []) {
  const ruleMap = new Map(rules.map(rule => [rule.process_id, rule]))
  const draftMap = new Map(drafts.map(rule => [rule.process_id, rule]))
  return steps.map(step => {
    const rule = draftMap.get(step.process_id) || ruleMap.get(step.process_id)
    return {
      process_id: step.process_id,
      process_name: step.process_name,
      rule_type: rule?.rule_type || 'required',
      options: (rule?.options || rule?.config?.options || []).map(option => ({
        code: option.code,
        label: option.label,
        skip_process_ids: [...option.skip_process_ids],
      })),
    }
  })
}


export function snapshotRouteRules(steps) {
  return steps.map(step => ({
    process_id: step.process_id,
    rule_type: step.rule_type,
    options: (step.options || []).map(option => ({
      ...option,
      skip_process_ids: [...option.skip_process_ids],
    })),
  }))
}
