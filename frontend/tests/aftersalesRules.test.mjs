import test from 'node:test'
import assert from 'node:assert/strict'

import {
  approvalSteps,
  buildEnglishReply,
  canCopyReply,
  canEditCase,
  compensationRatio,
  validateEnglishReply,
  validateActionDetails,
} from '../src/views/aftersales/aftersalesRules.js'


test('submitted cases are locked for the salesperson', () => {
  assert.equal(canEditCase('awaiting_sales_decision'), true)
  assert.equal(canEditCase('returned'), true)
  assert.equal(canEditCase('awaiting_supervisor'), false)
  assert.equal(canEditCase('approved'), false)
})

test('English reply can only be copied after final approval', () => {
  assert.equal(canCopyReply('awaiting_director'), false)
  assert.equal(canCopyReply('approved'), true)
  assert.equal(canCopyReply('processing'), true)
  assert.equal(canCopyReply('closed'), true)
})

test('non-compensation approval route marks director as skipped', () => {
  const steps = approvalSteps({ current_status: 'awaiting_supervisor', has_compensation: false })
  assert.equal(steps[4].label, '无需终审')
})

test('compensation approval route keeps director review', () => {
  const steps = approvalSteps({ current_status: 'awaiting_director', has_compensation: true })
  assert.equal(steps[4].label, '销售总监终审')
  assert.equal(steps[4].state, 'active')
})

test('compensation ratio is stable and handles zero goods value', () => {
  assert.equal(compensationRatio('420', '1150'), '36.5%')
  assert.equal(compensationRatio('420', '0'), '—')
})

test('compensation English reply requires approval caveat', () => {
  assert.equal(
    validateEnglishReply(true, 'We propose replacement subject to final internal approval.'),
    '',
  )
  assert.match(validateEnglishReply(true, 'We will replace it.'), /final internal approval/)
  assert.equal(validateEnglishReply(false, 'Please return the affected hair for inspection.'), '')
})

test('switching actions refreshes a safe English customer reply', () => {
  const compensation = buildEnglishReply([{ code: 'replacement' }])
  const inspection = buildEnglishReply([{ code: 'return_inspection', freight_payer: 'customer' }])

  assert.match(compensation, /replacement/i)
  assert.match(compensation, /subject to final internal approval/i)
  assert.match(inspection, /return the affected product/i)
  assert.doesNotMatch(inspection, /subject to final internal approval/i)
})

test('evidence waiver is represented as a supervisor step', () => {
  const steps = approvalSteps({ current_status: 'awaiting_evidence_waiver', has_compensation: false })
  assert.equal(steps[3].label, '证据豁免确认')
  assert.equal(steps[3].state, 'active')
})

test('action details block an incomplete approval package', () => {
  assert.match(validateActionDetails([{ code: 'return_inspection', freight_payer: 'customer' }]), /退回地址/)
  assert.equal(validateActionDetails([{ code: 'cash_refund', amount_usd: 100, currency: 'USD' }]), '')
})
