import test from 'node:test'
import assert from 'node:assert/strict'
import { bindingReviewPayload, validateBindingReceipt } from '../src/views/portal/bindingReview.mjs'
import { createAccessMutation } from '../src/views/portal/customerAccess.mjs'
const context = { review_fingerprint: 'a'.repeat(64), assignments: [{ id: '9007199254740993' }], identities: [{ id: '91' }], pending_requests: [{ id: 'order-1' }, { id: 'order-2' }] }
const form = { action: 'transfer', assignment_id: '9007199254740993', pending_request_ids: [], history_policy: 'remove', history_days: 30, reason: ' reviewed ', identity_id: '91' }
test('transfer includes only explicit orders, stable string ID and current fingerprint', () => {
  assert.deepEqual(bindingReviewPayload(context, form), { review_fingerprint: context.review_fingerprint, reason: 'reviewed', assignment_id: form.assignment_id, pending_request_ids: [], history_policy: 'remove', history_days: null })
  assert.throws(() => bindingReviewPayload(context, { ...form, assignment_id: 'other' }))
  for (const ids of [['foreign'], ['order-1', 'order-1']]) assert.throws(() => bindingReviewPayload(context, { ...form, pending_request_ids: ids }))
})
test('historical access requires explicit bounded duration', () => {
  for (const days of [null, 0, 366, 1.5]) assert.throws(() => bindingReviewPayload(context, { ...form, history_policy: 'explicit_grant', history_days: days }))
  assert.equal(bindingReviewPayload(context, { ...form, history_policy: 'explicit_grant' }).history_days, 30)
})
test('rebind requires current valid candidate and completed customer/assignment review', () => {
  const input = { ...form, action: 'rebind' }
  assert.deepEqual(bindingReviewPayload(context, input), { review_fingerprint: context.review_fingerprint, reason: 'reviewed', identity_id: '91' })
  for (const key of ['requires_assignment_review', 'customer_requires_review']) assert.throws(() => bindingReviewPayload({ ...context, [key]: true }, input))
  assert.throws(() => bindingReviewPayload(context, { ...input, identity_id: 'foreign' }))
  assert.throws(() => bindingReviewPayload({ ...context, review_fingerprint: '' }, input))
})
test('malformed or mismatched transfer receipt freezes and cannot be replayed', async () => {
  let writes = 0
  const operation = { action: 'transfer', id: 'access', version: 1, body: { pending_request_ids: ['order-1'] } }
  const mutation = createAccessMutation(async value => { writes++; return validateBindingReceipt(value, { id: 'access', row_version: 2, status: 'suspended', requires_enable: true, reassigned_request_ids: [], unassigned_pending_request_ids: [], history_grants: 0 }) })
  await assert.rejects(mutation.execute(operation)); assert.equal(mutation.state, 'uncertain')
  await assert.rejects(mutation.execute(operation)); await assert.rejects(mutation.execute()); assert.equal(writes, 1)
})
test('valid rebind receipt succeeds; missing impact receipt remains unknown', () => {
  const result = { status: 'suspended', requires_enable: true, expired_quotes: 2 }
  assert.equal(validateBindingReceipt({ action: 'rebind' }, result), result)
  assert.throws(() => validateBindingReceipt({ action: 'rebind' }, { ...result, expired_quotes: undefined }))
  assert.throws(() => validateBindingReceipt({ action: 'rebind' }, { ...result, status: 'enabled' }))
})
