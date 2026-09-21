import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
function setup(file, names, api) {
  const source = readFileSync(new URL(file, import.meta.url), 'utf8').match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*$/gm, '')
  const mocks = { ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }), defineProps: () => ({ invoiceId: 42, receiptId: 7 }), defineEmits: () => () => {}, ...api }
  return new Function(...Object.keys(mocks), source + `\nreturn {${names}}`)(...Object.values(mocks))
}
const invoice = '../src/views/invoice/components/InvoiceLifecycle.vue'
const receipt = '../src/views/receipt/ReceiptRemoteChange.vue'
test('cancellation lost response refreshes durable state without repeating POST', async () => {
  let posts=0, gets=0
  const vm=setup(invoice,'open,act,data,error',{
    ElMessageBox:{prompt:async()=>({value:'已核实原订单及关联货款，请取消'})},
    getInvoiceLifecycle:async()=>{gets++;return {version:'v1',cancellation:{status:posts?'uncertain':'pending'}}},
    applyInvoiceLifecycle:async(id,body)=>{posts++;assert.equal(body.expected_version,'v1');throw Error('timeout')}
  })
  await vm.open();await vm.act('remove')
  assert.equal(posts,1);assert.equal(gets,2);assert.equal(vm.data.value.cancellation.status,'uncertain');assert.ok(vm.error.value)
})
test('confirmation in flight excludes a second lifecycle action', async () => {
  let resolve, prompts=0, posts=0
  const vm=setup(invoice,'open,act',{
    ElMessageBox:{prompt:()=>{prompts++;return new Promise(r=>{resolve=r})}},
    getInvoiceLifecycle:async()=>({version:'v'}),applyInvoiceLifecycle:async()=>{posts++}
  })
  await vm.open();const first=vm.act('begin');await vm.act('begin');assert.equal(prompts,1)
  resolve({value:'客户确认终止原订单并核实货款安排'});await first;assert.equal(posts,1)
})
test('receipt stale evidence clears approval and requires a new preview', async () => {
  let posts=0
  const vm=setup(receipt,'open,accept,proof,reason,confirmed',{
    previewReceiptRemoteChange:async()=>({version:2,evidence_hash:'h',before:{},after:null}),
    acceptReceiptRemoteChange:async(id,body)=>{posts++;assert.equal(body.evidence_hash,'h');throw {response:{data:{detail:'远端已变化'}}}}
  })
  await vm.open();vm.reason.value='已核对原回款及实际资金去向';vm.confirmed.value=true
  await vm.accept();await vm.accept();assert.equal(posts,1);assert.equal(vm.proof.value,null);assert.equal(vm.confirmed.value,false)
})
