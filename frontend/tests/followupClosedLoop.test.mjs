import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import { createSSRApp } from 'vue'
import { renderToString } from 'vue/server-renderer'
import { emptyForm, formToPayload } from '../src/views/domestic_followup/followupDraft.js'
import { nextStepValidation, nextStepsFromAi, nextStepsPayload, normalizeNextSteps } from '../src/views/domestic_followup/followupNextSteps.js'
import { dictOptionLabels } from '../src/views/domestic_followup/followupDynamicOptions.js'

const customerStep = { step_key: 'customer', text: '客户约定回访', basis: 'customer_agreed', trigger: 'date', date: '2026-11-20', default_selected: true }
const actionStep = { step_key: 'action', text: '协调技术', basis: 'our_commitment', trigger: 'date', date: '2026-11-18', default_selected: false, commitment_advice: true }

async function followupTestServer(t, modules) {
  const server = await createServer({
    root: fileURLToPath(new URL('..', import.meta.url)), configFile: false, envFile: false, logLevel: 'silent',
    server: { middlewareMode: true, hmr: false },
    plugins: [{
      name: 'mock-followup',
      resolveId(id) { if (Object.hasOwn(modules, id)) return `\0${id}` },
      load(id) { if (id.startsWith('\0')) return modules[id.slice(1)] },
    }],
  })
  t.after(() => server.close())
  return server
}

test('a managed customer AI draft can save with unselected next steps and a legacy date', async t => {
  const draft = {
    id: 7, version: 1, ai_status: 'done', followup_date: '2026-11-17', attachments: [],
    ai_result: { customer_id: 12, customer_confidence: 0.9, summary: '已回复报价咨询',
      next: { date: actionStep.date, plan: actionStep.text }, next_steps: [actionStep] },
  }
  const modules = {
    '@/api/domesticFollowup': `
      export const submissions = []
      export const apiError = (error, fallback) => error.message || fallback
      export const followupApi = {
        dicts: async () => ({}), draft: async () => (${JSON.stringify(draft)}),
        tasks: async () => ({ items: [] }), collaboration: async () => ({}),
        timeline: async () => ({ customer: { id: 12, writable: true, responsibility_version: 1 }, open_items: [] }),
        confirmDraft: async (id, body) => { submissions.push({ id, body }); return {} },
      }
    `,
    '@/utils/feedback': `
      export const msgError = text => { throw new Error(text) }
      export const msgSuccessText = () => {}
      export const msgWarning = text => { throw new Error(text) }
    `,
    '@/utils/datetime': `export const currentBeijingDate = () => '2026-11-18'`,
  }
  const server = await followupTestServer(t, modules)
  const { useFollowupComposer } = await server.ssrLoadModule('/src/views/domestic_followup/composables/useFollowupComposer.js')
  const { submissions } = await server.ssrLoadModule('@/api/domesticFollowup')
  let composer
  await renderToString(createSSRApp({ setup() { composer = useFollowupComposer(); return () => null } }))
  await composer.resume(draft.id)
  const form = composer.form.value
  form.result_code = '有效沟通'

  assert.equal(composer.step.value, 'review')
  assert.equal(composer.canSave.value, true, 'a hidden legacy field must not disable confirmation')
  form.nextSteps = normalizeNextSteps(form.nextSteps.map(row => ({ ...row, selected: true })))
  assert.equal(composer.canSave.value, false, 'a selected primary step still needs a purpose')
  assert.match(composer.saveBlocker.value, /计划用途/)
  form.nextSteps[0].plan_purpose = 'maintenance'
  assert.equal(composer.canSave.value, true, 'the visible primary purpose is sufficient')
  form.nextSteps[0].due_date = null
  assert.equal(composer.canSave.value, false, 'a selected step still needs a date')
  assert.match(composer.saveBlocker.value, /填写日期/)
  form.nextSteps = normalizeNextSteps(form.nextSteps.map(row => ({ ...row, selected: false })))

  await composer.confirm()
  assert.equal(submissions.length, 1)
  assert.equal(submissions[0].body.result_code, '有效沟通')
  assert.equal(submissions[0].body.next_date, null)
  assert.deepEqual(submissions[0].body.next_steps, [])
})

test('recording from history carries the saved preparation into the follow-up without creating a card', async t => {
  const customer = { id: 12, shop_name: '回访测试店' }
  const card = {
    id: 23, customer_id: 12, template_code: 'T06', template_version: 2, goal: '确认修剪效果',
    status: 'ready', readonly: false, answers: { affected_product: '试戴样品' },
    strategy_status: 'done', strategy: { key_questions: [{ q: '修剪后还有哪里需要调整？' }] },
  }
  const server = await followupTestServer(t, {
    '@/api/domesticFollowup': `
      export const prepWrites = []
      export const apiError = (error, fallback) => error.message || fallback
      export const followupApi = {
        prepContext: async () => ({ templates: [{ code: 'T03' }], history_count: 1 }),
        dicts: async () => ({}), tasks: async () => ({ items: [] }),
        timeline: async () => ({ customer: { id: 12, writable: true }, open_items: [] }),
        createPrep: async data => { prepWrites.push(data) },
        updatePrep: async (id, data) => { prepWrites.push({ id, data }) },
      }
    `,
    '@/utils/feedback': `
      export const msgError = text => { throw new Error(text) }
      export const msgWarning = text => { throw new Error(text) }
      export const msgSuccessText = () => {}
    `,
    '@/utils/datetime': `export const currentBeijingDate = () => '2026-11-23'`,
  })
  const { useFollowupComposer } = await server.ssrLoadModule('/src/views/domestic_followup/composables/useFollowupComposer.js')
  const { usePrepCard } = await server.ssrLoadModule('/src/views/domestic_followup/composables/usePrepCard.js')
  const { prepWrites } = await server.ssrLoadModule('@/api/domesticFollowup')
  let composer, preparation
  await renderToString(createSSRApp({ setup() {
    composer = useFollowupComposer()
    preparation = usePrepCard({ onRecord: composer.open })
    return () => null
  } }))

  await preparation.open({ customer })
  assert.equal(preparation.step.value, 1)
  await preparation.recordPrep(card)
  const form = composer.form.value
  assert.equal(preparation.visible.value, false)
  assert.equal(composer.visible.value, true)
  assert.equal(form.customer_id, customer.id)
  assert.equal(form.prep_id, card.id)
  assert.equal(form.template_code, 'T06')
  assert.equal(form.template_version, 2)
  assert.deepEqual(form.template_answers, {
    fields: { affected_product: '试戴样品' },
    questions: [{ q: '修剪后还有哪里需要调整？', answer: '', state: 'not_asked' }],
  })
  assert.equal(formToPayload(form).prep_id, card.id)
  assert.deepEqual(prepWrites, [])
})

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
