import { test } from 'node:test'
import assert from 'node:assert/strict'
import { historyLabel, revokeFeedback } from '../src/views/system/whatsappStatus.js'

test('revoked status alone does not confirm remote logout', () => {
  assert.equal(revokeFeedback({ status: 'revoked' }).confirmed, false)
  assert.equal(revokeFeedback({ status: 'revoked', revoke_state: 'revoked_confirmed' }).confirmed, true)
  assert.match(revokeFeedback({ status: 'revoke_pending' }).text, /未确认/)
})
test('history batch completion does not claim complete lifetime history', () => {
  assert.equal(historyLabel('batch_complete'), '本次历史批次结束')
  assert.equal(historyLabel('gap'), '历史存在缺口')
})
