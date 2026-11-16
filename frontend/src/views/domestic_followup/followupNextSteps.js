export function normalizeNextSteps(rows) {
  let primaryFound = false
  const result = rows.map(row => {
    const primary = Boolean(row.selected && row.is_primary && !primaryFound)
    if (primary) primaryFound = true
    return { ...row, is_primary: primary }
  })
  if (!primaryFound && result.some(row => row.selected)) {
    const first = result.find(row => row.selected)
    first.is_primary = true
  }
  return result
}

export function nextStepsFromAi(steps) {
  return normalizeNextSteps((steps || []).map(step => ({
    ...step, selected: Boolean(step.default_selected), is_primary: false,
    due_date: step.date || step.due_date || null, assignee_user_id: null,
    plan_purpose: null, method: step.method || null,
  })))
}

export function manualPrimaryStep(manual) {
  if (!manual?.next_date || !manual?.next_plan) return null
  return {
    step_key: 'manual-primary', text: manual.next_plan, selected: true, is_primary: true,
    basis: 'our_plan', trigger: 'date', due_date: manual.next_date, method: manual.next_method || null,
    assignee_user_id: manual.plan_assignee_user_id || null, plan_purpose: manual.plan_purpose || null,
    source: { kind: 'raw_text', label: '业务员填写', verified: true }, done_criteria: null,
  }
}

export function nextStepValidation(rows, hasResponsibility) {
  const selected = (rows || []).filter(row => row.selected)
  const primaryCount = selected.filter(row => row.is_primary).length
  const primary = selected.find(row => row.is_primary)
  const missingDates = selected.filter(row => !row.due_date).length
  const missingPurpose = Boolean(hasResponsibility && primary && !primary.plan_purpose)
  return {
    valid: Boolean(!selected.length || (primaryCount === 1 && primary && !missingDates && !missingPurpose)),
    missingDates, missingPurpose, primary, primaryCount,
    summary: selected.length ? `将生成 1 张约定跟进${selected.length > 1 ? `、${selected.length - 1} 张行动待办` : ''}` : '不生成待办',
  }
}

export function nextStepsPayload(rows) {
  return (rows || []).filter(row => row.selected && row.text?.trim() && row.due_date).map(row => ({
    step_key: row.step_key, text: row.text.trim(), assignee_user_id: row.assignee_user_id || null,
    due_date: row.due_date, method: row.method || null, basis: row.basis || 'ai_suggestion',
    trigger: row.trigger || 'date', event: row.event || null, done_criteria: row.done_criteria || null,
    source: row.source || {}, is_primary: Boolean(row.is_primary),
    plan_purpose: row.is_primary ? row.plan_purpose || null : null,
  }))
}
