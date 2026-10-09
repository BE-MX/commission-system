import test from 'node:test'
import assert from 'node:assert/strict'
import { proposalNotice, piNotice, snapshotTitle } from '../src/views/portal/presentation.mjs'

test('published PI does not inherit expiry warning from historical proposal', () => {
  const order = { status: 'invoice_created', proposal: { expired: true, accepted: true }, pi_amendment: { status: 'current' } }
  assert.equal(proposalNotice(order), '')
  assert.match(piNotice(order), /已确认并发布/)
  assert.match(snapshotTitle(order), /最近发布/)
})
test('accepted proposal must still be valid before initial PI approval', () => {
  assert.match(proposalNotice({ status: 'ready_for_review', proposal: { expired: true, accepted: true } }), /建 PI 前需要重新确认/)
})
test('withdrawn and voided PI explicitly label historical snapshot', () => {
  for (const status of ['withdrawn', 'voided', 'pending_customer', 'accepted', 'rejected']) {
    assert.match(piNotice({ status: 'invoice_created', pi_amendment: { status } }), /历史快照/)
  }
})
test('unknown PI state does not claim a valid document', () => {
  assert.match(piNotice({ status: 'invoice_created' }), /状态待核实/)
})
test('unaccepted proposal is never labelled customer confirmed', () => {
  assert.equal(snapshotTitle({ status: 'awaiting_customer', proposal: { accepted: false } }), '当前请求 / 提案商品信息')
  assert.equal(proposalNotice({ status: 'cancelled', proposal: { expired: true } }), '')
})
