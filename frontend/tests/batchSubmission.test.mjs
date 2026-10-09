import assert from 'node:assert/strict'
import test from 'node:test'
import { batchSubmissionKey, clearSubmission, copySubmission, isBatchReceipt, readSubmission, saveSubmission, uncertainSubmission } from '../src/views/receipt/batchSubmission.js'
const body = () => ({ request_key: 'original_request_123', amount: '10.00', bank_charge: '0', collection_date: '2026-10-06', payment_type: 'T/T', remark: 'original', attachment_ids: ['proof'], allocations: [{ invoice_id: 1, amount: '10.00', settlement_id: null, balance_version: 'a'.repeat(64) }] })
function memory() { const data = new Map(); return { getItem: key => data.get(key) ?? null, setItem: (key,value) => data.set(key,value), removeItem: key => data.delete(key), data } }
test('pending body preserves exact financial representation and cannot be edited by an input reference', () => {
  const store = memory(), original = body(); saveSubmission(store,1,original)
  original.amount = '9'; original.allocations[0].balance_version = 'b'.repeat(64); original.attachment_ids.push('other')
  assert.deepEqual(readSubmission(store,1),body())
  const restored = readSubmission(store,1); restored.remark = 'changed'
  assert.equal(readSubmission(store,1).remark,'original')
})
test('one actor cannot restore another slot or overwrite unresolved content', () => {
  const store=memory(), original=body();saveSubmission(store,1,original)
  assert.equal(readSubmission(store,2),null)
  for(const changed of [{...original,request_key:'different_request_123'},{...original,remark:'edited'}]) assert.throws(()=>saveSubmission(store,1,changed))
  assert.deepEqual(readSubmission(store,1),original)
  clearSubmission(store,1,'different_request_123');assert.deepEqual(readSubmission(store,1),original)
  clearSubmission(store,1,original.request_key);assert.equal(readSubmission(store,1),null)
})
test('denied, silently dropped or corrupted storage never qualifies as durable', () => {
  const store=memory();store.setItem=()=>{throw new Error('quota')};assert.throws(()=>saveSubmission(store,1,body()))
  store.setItem=()=>{};assert.throws(()=>saveSubmission(store,1,body()))
  store.data.set(batchSubmissionKey(1),'not JSON');assert.throws(()=>readSubmission(store,1))
  store.data.set(batchSubmissionKey(1),JSON.stringify({actor:2,body:body()}));assert.throws(()=>readSubmission(store,1))
  for(const actor of [0,NaN,1.2])assert.throws(()=>readSubmission(store,actor))
})
test('only matching, complete authorized receipts can finish a pending command', () => {
  const original=body(), result={id:7,request_key:original.request_key,status:'active',items:[{invoice_id:1}]}
  assert.equal(isBatchReceipt(result,original),true);assert.equal(isBatchReceipt({...result,status:'voided'},original),true)
  for(const changed of [{...result,id:true},{...result,request_key:'wrong'},{...result,items:[]},{...result,items:[{invoice_id:2}]},{...result,status:'unknown'}])assert.equal(isBatchReceipt(changed,original),false)
  assert.deepEqual(copySubmission(original),original)
})
test('no transport result, timeout and all failures after an unknown result stay uncertain', () => {
  for(const error of [new Error('network'),{response:{status:503}},{response:{status:408}}])assert.equal(uncertainSubmission(error),true)
  assert.equal(uncertainSubmission({response:{status:409}}),false)
  for(const status of [401,403,404,409,422,503])assert.equal(uncertainSubmission({response:{status}},true),true)
})
