import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { emptyForm, formToPayload } from '../src/views/domestic_followup/followupDraft.js'
import { nextStepValidation, nextStepsFromAi, nextStepsPayload, normalizeNextSteps } from '../src/views/domestic_followup/followupNextSteps.js'
import { dictOptionLabels } from '../src/views/domestic_followup/followupDynamicOptions.js'

const customerStep = { step_key: 'customer', text: '客户约定回访', basis: 'customer_agreed', trigger: 'date', date: '2026-11-20', default_selected: true }
const actionStep = { step_key: 'action', text: '协调技术', basis: 'our_commitment', trigger: 'date', date: '2026-11-18', default_selected: false, commitment_advice: true }

test('only evidence-backed dated customer agreements are selected by default', () => {
  const rows = nextStepsFromAi([customerStep, actionStep,
    { step_key: 'shot', text: '截图约定', basis: 'customer_agreed', date: '2026-11-20', default_selected: false }])
  assert.deepEqual(rows.map(row => row.selected), [true, false, false])
  assert.equal(rows[0].is_primary, true)
  assert.equal(rows[1].commitment_advice, true)
})

test('selected steps always have exactly one primary and payload has no legacy plan', () => {
  let rows = nextStepsFromAi([customerStep, actionStep])
  rows = normalizeNextSteps(rows.map(row => ({ ...row, selected: true })))
  rows = normalizeNextSteps(rows.map((row, index) => ({ ...row, is_primary: index === 1 })))
  assert.equal(rows.filter(row => row.is_primary).length, 1)
  assert.equal(rows[1].is_primary, true)
  const form = { ...emptyForm('2026-11-16'), customer_id: 1, nextSteps: rows,
    next_date: '2026-11-20', next_plan: '旧字段', next_method: '微信' }
  const payload = formToPayload(form)
  assert.equal(payload.next_steps.length, 2)
  assert.equal(payload.next_date, null)
  assert.equal(payload.next_plan, null)
  assert.equal(nextStepsPayload(rows).filter(row => row.is_primary).length, 1)
})

test('manual primary replaces AI primary instead of creating a second primary', () => {
  const ai = nextStepsFromAi([customerStep, actionStep]).map(row => ({ ...row, selected: true }))
  const manual = { step_key: 'manual-primary', text: '手工主步骤', selected: true, is_primary: true, due_date: '2026-11-22', basis: 'our_plan' }
  const merged = normalizeNextSteps([manual, ...ai])
  assert.equal(merged.filter(row => row.is_primary).length, 1)
  assert.equal(merged[0].is_primary, true)
  assert.equal(nextStepValidation(merged, false).valid, true)
})

test('dynamic fields load dict-driven options from the system dictionary API', async () => {
  const source = await readFile(new URL('../src/views/domestic_followup/components/FollowupDynamicField.vue', import.meta.url), 'utf8')
  assert.match(source, /getDictItems/)
  assert.match(source, /field\.options\?\.dict/)
  assert.match(source, /options\?\.inline/)
  assert.deepEqual(dictOptionLabels([{ code: 'wechat', label: '微信' }, { code: 'phone', label: '电话' }]), ['微信', '电话'])
})

test('event steps need verification date and managed primary needs purpose', () => {
  const rows = nextStepsFromAi([{ ...customerStep, trigger: 'event', date: null }])
  assert.equal(nextStepValidation(rows, false).valid, false)
  assert.equal(nextStepValidation(rows, false).missingDates, 1)
  const dated = rows.map(row => ({ ...row, due_date: '2026-11-21' }))
  assert.equal(nextStepValidation(dated, true).missingPurpose, true)
  assert.equal(nextStepValidation(dated.map(row => ({ ...row, plan_purpose: 'maintenance' })), true).valid, true)
})
