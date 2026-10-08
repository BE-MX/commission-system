import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {assertOrderUnchanged, assertClaimedTask, buildPayload, createOne} from '../okki_outbound_creator.mjs';
import {failureEvidence, refreshFailedRetryPolicy} from '../okki_outbound_poller.js';

const order = {order_id:123, create_time:'2026-10-08 13:41:34', update_time:'2026-10-08 13:42:05',
  status:1, company_id:2, handler:[9,10], currency:'USD', exchange_rate:6.69, exchange_rate_usd:1,
  product_list:[{unique_id:6,product_id:4,sku_id:5,count:2,unit_price:29.55,enable_count:100,
    unit:'Piece',product_name:'Product A',product_model:'A',product_cn_name:'产品 A'},
  {unique_id:7,product_id:4,sku_id:5,count:8,unit_price:28.50,product_name:'Product A'}]};
const check = fresh => assertOrderUnchanged(order, fresh, 'INV123', 'Keep original remark');

test('inventory, timestamps and JSON property order do not prevent outbound submission',()=>{
  const fresh=structuredClone(order);
  fresh.update_time='2026-10-08 13:42:06';
  fresh.product_list[0].enable_count=90;
  fresh.product_list[0].real_count=123;
  fresh.product_list[0].to_outbound_count=0;
  assert.deepEqual(buildPayload(order,'INV123','remark'),buildPayload(fresh,'INV123','remark'));
  assert.doesNotThrow(()=>check(Object.fromEntries(Object.entries(fresh).reverse())));
});

test('row and handler order and equivalent numeric representations are stable',()=>{
  const fresh=structuredClone(order);
  fresh.order_id='123';fresh.company_id='2';fresh.handler=['10','9'];
  fresh.exchange_rate='6.6900';fresh.exchange_rate_usd='1.0000';
  for(const row of fresh.product_list){
    for(const field of ['unique_id','product_id','sku_id','count'])row[field]=String(row[field]);
    row.unit_price=Number(row.unit_price).toFixed(4);
  }
  fresh.product_list.reverse();
  assert.doesNotThrow(()=>check(fresh));
});

for(const [name,change] of [
  ['customer',x=>x.company_id=3],['handler',x=>x.handler=[11]],['currency',x=>x.currency='EUR'],
  ['exchange rate',x=>x.exchange_rate=6.70],['USD exchange rate',x=>x.exchange_rate_usd=2],
  ['status',x=>x.status=2],['deleted order',x=>x.removed=1],
  ['row ID',x=>x.product_list[0].unique_id=8],['product',x=>x.product_list[0].product_id=8],
  ['SKU',x=>x.product_list[0].sku_id=8],['quantity',x=>x.product_list[0].count=3],
  ['price',x=>x.product_list[0].unit_price=30],['unit',x=>x.product_list[0].unit='Box'],
  ['name',x=>x.product_list[0].product_name='Product B'],['model',x=>x.product_list[0].product_model='B'],
  ['Chinese name',x=>x.product_list[0].product_cn_name='产品 B'],
  ['removed row',x=>x.product_list.pop()],['added row',x=>x.product_list.push({...x.product_list[0],unique_id:8})],
  ['same SKU redistributed across rows',x=>{x.product_list[0].count=3;x.product_list[1].count=7;}],
])test(`${name} changes block before intent and retain a safe difference summary`,()=>{
  const fresh=structuredClone(order);change(fresh);
  assert.throws(()=>check(fresh),error=>{
    assert.equal(error.failure?.code,'order_changed');
    assert.ok(error.failure.changed_fields.length);
    assert.match(error.failure.before_digest,/^[a-f0-9]{64}$/);
    assert.match(error.failure.after_digest,/^[a-f0-9]{64}$/);
    assert.notEqual(error.failure.before_digest,error.failure.after_digest);
    assert.doesNotMatch(JSON.stringify(error.failure),/Product A|Keep original remark/);
    return error.uncertain !== true;
  });
});

test('duplicate row IDs and invalid numeric values fail closed',()=>{
  for(const change of [x=>x.product_list[1].unique_id=6,x=>x.product_list[0].unit_price='NaN',
    x=>x.product_list[0].unit_price='Infinity',x=>x.product_list[0].unique_id=9007199254740992,
    x=>x.product_list[0].unique_id='9007199254740992']){
    const fresh=structuredClone(order);change(fresh);
    assert.throws(()=>check(fresh));
  }
});

test('cancellation after claim still prevents a managed submission',()=>{
  for(const invoice_status of ['cancel_pending','cancelled']){
    assert.throws(()=>assertClaimedTask({status:'running',invoice_status,attempts:1,
      latest_sync_log_id:1207,sync_status:'synced',linked_sync_id:null,order_type:'stock'},1207,1),/changed/);
  }
});

test('decimal normalization preserves differences below floating point resolution',()=>{
  const original=structuredClone(order),fresh=structuredClone(order);
  original.product_list[0].unit_price='29.550000000000001';
  fresh.product_list[0].unit_price='29.550000000000002';
  assert.throws(()=>assertOrderUnchanged(original,fresh,'INV123',''),/Order changed/);
});

for(const changed of [false,true])test(`managed creation ${changed?'defers changed quantity':'accepts stock refresh'} before POST`,async t=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'ark-outbound-guard-'));
  t.after(()=>fs.rmSync(directory,{recursive:true,force:true}));
  const fresh=structuredClone(order);
  if(changed)fresh.product_list[0].count=3;
  else fresh.product_list[0].enable_count=99;
  let posts=0;
  const options={directory,invoiceNo:'INV123',invoiceRemark:'remark',beforeSubmit:async original=>{
    assertOrderUnchanged(original,fresh,'INV123','remark');
  },api:async(route,payload)=>{
    if(payload){posts++;return {outbound_invoice_id:88,serial_id:'INV123'};}
    if(route.includes('/order/info'))return order;
    if(route.includes('/outbound/list'))return {count:0,list:[]};
    if(route.includes('serial_id='))return null;
    return {outbound_invoice_id:88,serial_id:'INV123',company_info:{id:2},status:1,remark:'remark',
      record_list:buildPayload(order,'INV123','remark').record_list};
  }};
  if(changed){
    await assert.rejects(createOne('123',options),/Order changed/);
    assert.equal(posts,0);
    assert.equal(fs.existsSync(path.join(directory,'logs','ark-outbound-intents')),false);
  }else{
    assert.equal((await createOne('123',options)).outcome,'created');assert.equal(posts,1);
  }
});

test('retry evidence retains changed paths and actual backoff without raw values',async()=>{
  let failure;
  const fresh=structuredClone(order);fresh.product_list[0].count=3;
  try{check(fresh);}catch(error){failure=error.failure;}
  const output='Order changed before outbound submission; no creation attempted\nARK_OUTBOUND_FAILURE='+JSON.stringify(failure)+'\n';
  const evidence=JSON.parse(failureEvidence({attempts:1},output,5));
  assert.equal(evidence.retry_delay_minutes,10);
  assert.deepEqual(evidence.failure,failure);
  const writes=[];
  await refreshFailedRetryPolicy({query:async(sql,params)=>{
    if(sql.startsWith('SELECT'))return [[{id:1,attempts:1,last_error:JSON.stringify(evidence)}]];
    writes.push(JSON.parse(params[0]));return [{affectedRows:1}];
  }},8);
  assert.equal(writes.length,1);
  assert.equal(writes[0].max_attempts,8);
  assert.deepEqual(writes[0].failure,failure);
});

test('malformed or untrusted change metadata is not accepted as structured evidence',()=>{
  const metadata={code:'order_changed',before_digest:'a'.repeat(64),after_digest:'b'.repeat(64),
    changed_fields:['record_list.6.outbound_count']};
  for(const change of [x=>x.changed_fields=['customer-secret@example.invalid'],
    x=>x.before_digest='secret',x=>x.code='submitted',x=>x.changed_fields=Array(21).fill('currency')]){
    const value=structuredClone(metadata);change(value);
    assert.equal(JSON.parse(failureEvidence({attempts:1},'ARK_OUTBOUND_FAILURE='+JSON.stringify(value),5)).failure,undefined);
  }
  assert.equal(JSON.parse(failureEvidence({attempts:1},'ARK_OUTBOUND_FAILURE={',5)).failure,undefined);
});
