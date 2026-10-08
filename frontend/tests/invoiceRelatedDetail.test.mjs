import test from 'node:test'
import assert from 'node:assert/strict'
import { mergeAnomalyOverview, progressValue, createDetailSession } from '../src/views/invoice/composables/invoiceDetailState.js'

test('transient read failure retains confirmed warnings, normal response clears, permission loss discards', () => {
  const first = mergeAnomalyOverview({}, {order:{state:'ready',has_anomaly:true}})
  const failed = mergeAnomalyOverview(first,{})
  assert.equal(failed.order.has_anomaly,true)
  assert.equal(failed.order.state,'unavailable')
  assert.equal(mergeAnomalyOverview(failed,{order:{state:'ready',has_anomaly:false}}).order.has_anomaly,false)
  assert.equal(mergeAnomalyOverview(failed,{order:{state:'restricted',has_anomaly:true}}).order.has_anomaly,false)
})
test('progress hides unverified and zero bases, does not round into completion, preserves excess', () => {
  assert.equal(progressValue(0,0,'ready'),null)
  assert.equal(progressValue(50,100,'unverified'),null)
  assert.deepEqual(progressValue('99.99','100','ready'),{percentage:99.9,complete:false,over:0})
  assert.deepEqual(progressValue(120,100,'ready'),{percentage:100,complete:true,over:20})
})
test('switch or close aborts and invalidates stale invoice reads', () => {
  const session = createDetailSession(), first = session.begin(), second = session.begin()
  assert.equal(first.signal.aborted,true)
  assert.equal(session.current(first.version),false)
  assert.equal(session.current(second.version),true)
  session.cancel()
  assert.equal(second.signal.aborted,true)
  assert.equal(session.current(second.version),false)
})
