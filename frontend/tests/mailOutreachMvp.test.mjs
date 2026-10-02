import assert from 'node:assert/strict'
import test from 'node:test'
import { nextTick, reactive } from 'vue'
import { readFileSync } from 'node:fs'
import { parse, compileScript, compileTemplate } from '@vue/compiler-sfc'
import { viewController } from './helpers/viewController.mjs'
import * as presentation from '../src/views/mail_outreach/presentation.js'
import * as validators from '../src/utils/validators.js'
import { createLatestResource } from '../src/views/customer_hub/customerHubResources.js'

const reviewPath = '../../src/views/customer_hub/mail_outreach/MailOutreachReviewDrawer.vue'
const fixture = () => ({ id: 4, status: 'draft', to_email: 'recipient@example.com', verification_status: 'valid', contactability_status: 'allowed', revision: { id: 10, content_sha256: 'a'.repeat(64), subject: 'Hello', body_text: 'Good morning', claims: [{ claim: 'Fact', fact_id: 8 }], risk_flags: [], schedule_policy: { office_start: '09:00' } } })
function review(t, overrides = {}) {
  const data = fixture(), calls = []
  const { vm, messages } = viewController(t, reviewPath, 'reload, detail, revision, claims, riskFlags, editForm, approveForm, preview, manualBeijing, scheduledAtUtc, reviewed, canApprove, approve, saveRevision, regenerate, runPreview, saving, dirty, mailboxes', {
    '@props': reactive({ draftId: 4, modelValue: true }),
    '@/views/mail_outreach/presentation': presentation,
    '@/api/mailOutreach': { getDraft: async () => ({ data: structuredClone(data) }), listMailboxes: async () => ({ data: [{ id: 1, status: 'active', auth_status: 'active' }] }), approveDraft: async (id, payload) => calls.push({ id, payload }), createRevision: async () => {}, ...overrides },
  })
  return { vm, data, calls, messages }
}
async function ready(vm) {
  await vm.reload(); await nextTick()
  vm.manualBeijing.value = '2099-10-02 00:05:00'
  await nextTick(); vm.reviewed.value = true
}
test('review uses API claims/risk fields and exact approve schema with manual Beijing midnight', async t => {
  const { vm, calls } = review(t)
  await ready(vm)
  assert.equal(vm.claims.value[0].fact_id, 8)
  assert.equal(vm.scheduledAtUtc.value, '2099-10-01T16:05:00.000Z')
  assert.equal(vm.canApprove.value, true)
  await vm.approve()
  assert.deepEqual(Object.keys(calls[0].payload).sort(), ['expected_content_sha256', 'mailbox_binding_id', 'reason', 'revision_id', 'schedule_policy', 'scheduled_at_utc'].sort())
  assert.deepEqual(calls[0].payload.schedule_policy, { office_start: '09:00' })
})
test('approval blocks risks, unverified recipient, expired sender, missing human review and stale time', async t => {
  const { vm } = review(t); await ready(vm)
  vm.reviewed.value = false; assert.equal(vm.canApprove.value, false); vm.reviewed.value = true
  vm.detail.value.revision.risk_flags = [{ code: 'generation_not_ready', detail: 'not ready' }]; assert.equal(vm.canApprove.value, false)
  vm.detail.value.revision.risk_flags = []; vm.detail.value.verification_status = 'unknown'; assert.equal(vm.canApprove.value, false)
  vm.detail.value.verification_status = 'valid'; vm.mailboxes.value[0].auth_status = 'expired'; assert.equal(vm.canApprove.value, false)
  vm.mailboxes.value[0].auth_status = 'active'; vm.manualBeijing.value = '2000-01-01 00:00:00'; await nextTick(); vm.reviewed.value = true; assert.equal(vm.canApprove.value, false)
})
test('saving revision reloads new hash while saving flag is set and requires fresh review', async t => {
  let reads = 0
  const { vm } = review(t, { getDraft: async () => { const data = fixture(); reads++; data.revision.id = reads; data.revision.subject = reads === 1 ? 'Hello' : 'Changed'; data.revision.content_sha256 = String(reads).repeat(64); return { data } } })
  await ready(vm); vm.editForm.subject = 'Changed'; await vm.saveRevision()
  assert.equal(reads, 2); assert.equal(vm.revision.value.id, 2); assert.equal(vm.dirty.value, false); assert.equal(vm.reviewed.value, false); assert.equal(vm.canApprove.value, false)
})
test('regenerate sends explicit regenerate payload and consumes returned current revision', async t => {
  const writes = []; const { vm } = review(t, { createRevision: async (...args) => writes.push(args) })
  await ready(vm); await vm.regenerate()
  assert.deepEqual(writes, [[4, { regenerate: true }]]); assert.equal(vm.reviewed.value, false)
})
test('manual selection overrides a prior candidate and editing invalidates per-message confirmation', async t => {
  const { vm } = review(t); await ready(vm)
  vm.preview.value = { scheduled_at_utc: '2099-12-10T10:00:00Z' }
  assert.equal(vm.scheduledAtUtc.value, '2099-10-01T16:05:00.000Z')
  vm.editForm.body_text = 'Changed'; await nextTick(); assert.equal(vm.reviewed.value, false); assert.equal(vm.canApprove.value, false)
})
test('recipient candidate import never asserts verification or contact permission', async t => {
  const calls = []
  const { vm } = viewController(t, '../../src/views/customer_hub/mail_outreach/MailRecipientPreparation.vue', 'form, context, selectCandidate, save, canSave', {
    '@props': { customerId: 3 }, '@/utils/validators': validators,
    '../customerHubResources': { createLatestResource }, '@/views/mail_outreach/presentation': presentation,
    '@/api/mailOutreach': { getOutreachContext: async () => ({ data: { contacts: [], contact_candidates: [{ fact_id: 7, source_url: 'https://example.com', display_name: 'Current name', email: 'current@example.com', language_tag: 'en', timezone: 'Europe/London', country_code: 'GB', value_json: { name: 'Person', email: 'person@example.com', verified: true, contact_allowed: true } }] } }), saveRecipient: async (...args) => calls.push(args) },
  })
  await vm.context.load(3); vm.selectCandidate(7)
  assert.equal(vm.form.verified, false); assert.equal(vm.form.contact_allowed, false)
  assert.equal(vm.form.email, 'current@example.com'); assert.equal(vm.form.display_name, 'Current name'); assert.equal(vm.form.country_code, 'GB')
  vm.form.country_code = ''; assert.equal(vm.canSave.value, false); vm.form.country_code = 'gb'
  vm.form.language_tag = 'en'; vm.form.timezone = 'Europe/London'; vm.form.verification_basis = 'Confirmed directly'
  assert.equal(vm.canSave.value, true); await vm.save()
  assert.equal(calls[0][1].country_code, 'GB'); assert.equal(calls[0][1].source_fact_id, 7); assert.equal(calls[0][1].verified, false); assert.equal(calls[0][1].contact_allowed, false)
})
test('mailbox edits omit immutable sender and never carry credentials or status metadata', async t => {
  const calls = []
  const { vm } = viewController(t, '../../src/views/mail_outreach/MailboxSettings.vue', 'open, form, save', {
    './presentation': presentation, '@/utils/validators': validators,
    '@/api/mailOutreach': { updateMailbox: async (...args) => calls.push(args), getMailStatus: async () => ({ data: { mailboxes: [] } }) },
  })
  vm.open({ id: 5, sender_email: 'sender@example.com', worker_identity: 'worker', cli_workspace: 'mail', auth_status: 'active', secret_ref: 'must-not-copy', watch_health: 'healthy' })
  await vm.save(); assert.equal(calls[0][0], 5); assert.equal('sender_email' in calls[0][1], false); assert.equal('secret_ref' in calls[0][1], false); assert.equal('watch_health' in calls[0][1], false)
})
test('modified mail Vue templates compile', () => {
  for (const path of ['customer_hub/mail_outreach/MailOutreachPanel.vue', 'customer_hub/mail_outreach/MailOutreachReviewDrawer.vue', 'customer_hub/mail_outreach/MailRecipientPreparation.vue', 'mail_outreach/MailOutreachQueue.vue', 'mail_outreach/MailboxSettings.vue', 'mail_outreach/MailInboundEvents.vue']) {
    const filename = new URL('../src/views/' + path, import.meta.url).pathname
    const { descriptor, errors } = parse(readFileSync(new URL('../src/views/' + path, import.meta.url), 'utf8'), { filename })
    assert.deepEqual(errors, []); compileScript(descriptor, { id: path })
    assert.deepEqual(compileTemplate({ source: descriptor.template.content, filename, id: path }).errors, [])
  }
})
test('obsolete schedule responses cannot replace a newly loaded revision', async t => {
  let finish
  const { vm } = review(t, { previewSchedule: () => new Promise(resolve => { finish = resolve }) })
  await ready(vm)
  const pending = vm.runPreview()
  await vm.reload()
  finish({ data: { scheduled_at_utc: '2099-10-01T10:00:00Z' } })
  await pending
  assert.equal(vm.preview.value, null); assert.equal(vm.reviewed.value, false)
})
test('event classification requires a reason, posts only classification and reason, and refreshes', async t => {
  const calls = []
  const { vm } = viewController(t, '../../src/views/mail_outreach/MailInboundEvents.vue', 'open, form, save', {
    './presentation': presentation,
    '@/api/mailOutreach': { listMailEvents: async () => ({ data: { items: [], total: 0 } }), classifyMailEvent: async (...args) => calls.push(args) },
  })
  vm.open({ id: 20, classification: 'other', matched_customer_id: 3 })
  await vm.save(); assert.equal(calls.length, 0)
  vm.form.reason = 'Explicit unsubscribe request'; vm.form.classification = 'opt_out'
  await vm.save(); assert.deepEqual(calls, [[20, { classification: 'opt_out', reason: 'Explicit unsubscribe request' }]])
})
