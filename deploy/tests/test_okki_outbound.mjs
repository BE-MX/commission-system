import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createOne, findExisting, buildPayload, requestOkki} from '../okki_outbound_creator.mjs';
const order = {order_id: 123, create_time: '2026-09-17 08:00:00', handler: [9], company_id: 2,
  currency: 'USD', exchange_rate: 669, exchange_rate_usd: 100,
  product_list: [{product_id: 4, sku_id: 5, unique_id: 6, count: 2, unit_price: 10, to_outbound_count: 0}]};
function dir(t) {const d=fs.mkdtempSync(path.join(os.tmpdir(),'ark-outbound-test-')); t.after(()=>fs.rmSync(d,{recursive:true,force:true})); return d;}
test('manual pending outbound with zero order outbound count prevents POST', async t => {
  let posts=0;
  const result=await createOne('123',{invoiceNo:'INV123',directory:dir(t),api:async (route, payload)=> {
    if(payload) {posts++; throw Error('Must not POST');}
    if(route.includes('/order/info')) return order;
    if(route.includes('/outbound/list')) return {count:1,list:[{outbound_invoice_id:88,serial_id:'MANUAL'}]};
    return {record_list:[{order_id:123,outbound_count:1}]};
  }});
  assert.equal(result.outcome,'existing'); assert.equal(posts,0);
});
test('lookup errors fail closed before submission', async t=> {
  let posts=0;
  await assert.rejects(createOne('123',{invoiceNo:'INV123',directory:dir(t),api:async(route,payload)=> {
    if(payload) posts++;
    if(route.includes('/order/info')) return order;
    throw Error('lookup unavailable');
  }}),/lookup unavailable/);
  assert.equal(posts,0);
});
test('lost POST response writes intent; next attempt never posts again', async t=> {
  const directory=dir(t); let posts=0;
  const api=async(route,payload)=> {
    if(payload) {posts++; throw Error('response lost');}
    if(route.includes('/order/info')) return order;
    return {count:0,list:[]};
  };
  await assert.rejects(createOne('123',{invoiceNo:'INV123',directory,api}), e=>e.uncertain===true);
  await assert.rejects(createOne('123',{invoiceNo:'INV123',directory,api}),/Prior submission intent/);
  assert.equal(posts,1);
});
test('live association resolves prior uncertain intent without another POST',async t=> {
  const directory=dir(t); let posts=0; let created=false;
  const api=async(route,payload)=> {
    if(payload) {posts++; created=true; throw Error('response lost');}
    if(route.includes('/order/info')) return order;
    if(route.includes('/outbound/list')) return created?{count:1,list:[{outbound_invoice_id:88}]}:{count:0,list:[]};
    return {record_list:[{order_id:123}]};
  };
  await assert.rejects(createOne('123',{invoiceNo:'INV123',directory,api}));
  assert.equal((await createOne('123',{invoiceNo:'INV123',directory,api})).outcome,'existing'); assert.equal(posts,1);
});
test('successful creation verifies association and persists ledger',async t=> {
  const directory=dir(t);let posts=0;
  const result=await createOne('123',{invoiceNo:'INV123',directory,api:async(route,payload)=> {
    if(payload) {posts++; assert.equal(payload.status,1); assert.equal(payload.serial_id,'INV123'); return {outbound_invoice_id:88,serial_id:'INV123'};}
    if(route.includes('/order/info')) return order;
    if(route.includes('/outbound/list')) return {count:0,list:[]};
    return {record_list:[{order_id:123}]};
  }});
  assert.equal(result.outcome,'created');assert.equal(posts,1);
  assert.match(fs.readFileSync(path.join(directory,'logs','created-outbound.jsonl'),'utf8'),/INV123/);
});
test('invalid product stops whole order instead of partial creation',()=> {
  assert.throws(()=>buildPayload({...order,product_list:[...order.product_list,{count:1}]}, 'INV123'),/Invalid order item/);
});
test('pagination examines second page and partial outbound counts as existing',async()=> {
  const result=await findExisting(order,async route=> {
    if(route.includes('start_index=1')) return {count:2,list:[{outbound_invoice_id:80}]};
    if(route.includes('start_index=2')) return {count:2,list:[{outbound_invoice_id:81}]};
    return {record_list:[{order_id:route.endsWith('81')?123:999,outbound_count:1}]};
  }); assert.equal(result.outbound_invoice_id,81);
});
test('dry run does not create ledger or intent',async t=> {
  const directory=dir(t);
  const result=await createOne('123',{invoiceNo:'INV123',directory,dryRun:true,api:async(route,payload)=> {
    assert.equal(payload,undefined);return route.includes('/order/info')?order:{count:0,list:[]};
  }});assert.equal(result.outcome,'dry_run');assert.deepEqual(fs.readdirSync(directory),[]);
});
test('concurrent creators share exclusive intent; only one POST',async t=> {
  const directory=dir(t);let posts=0;
  const api=async(route,payload)=> {
    if(payload) {posts++;await new Promise(r=>setTimeout(r,20));return {outbound_invoice_id:88,serial_id:'INV123'};}
    if(route.includes('/order/info')) return order;
    if(route.includes('/outbound/list')) return {count:0,list:[]};
    return {record_list:[{order_id:123}]};
  };
  const results=await Promise.allSettled([createOne('123',{invoiceNo:'INV123',directory,api}),createOne('123',{invoiceNo:'INV123',directory,api})]);
  assert.equal(posts,1);assert.equal(results.filter(r=>r.status==='fulfilled').length,1);
});

const {resultFromOutput, finishTask, claimBatch} = await import('../okki_outbound_poller.js');
test('zero exit without validated result never marks done',()=> {
  assert.equal(resultFromOutput(0, 'failed but exit zero', '123'),null);
  assert.equal(resultFromOutput(0, 'ARK_OUTBOUND_RESULT={"outcome":"created","order_id":"999","outbound_invoice_id":88}', '123'),null);
  assert.equal(resultFromOutput(1, 'ARK_OUTBOUND_RESULT={"outcome":"created","order_id":"123","outbound_invoice_id":88}', '123'),null);
  assert.equal(resultFromOutput(0, 'ARK_OUTBOUND_RESULT={"outcome":"existing","order_id":"123","outbound_invoice_id":88}', '123').outcome,'existing');
});
test('claim leases only one task immediately and increments attempt version',async()=> {
  const calls=[];
  const result=await claimBatch({query:async(sql,params)=> {
    calls.push({sql,params});return calls.length===1?[[{id:7,order_id:'123',attempts:2}]]:[{affectedRows:1}];
  }});
  assert.equal(calls[0].params.at(-1),1);assert.equal(result.length,1);assert.equal(result[0].attempts,3);
});
test('lost optimistic claim does not execute task',async()=> {
  let calls=0;
  const result=await claimBatch({query:async()=> ++calls===1?[[{id:7,attempts:0}]]:[{affectedRows:0}]});
  assert.deepEqual(result,[]);
});
test('stale worker cannot overwrite new claim result',async()=> {
  await assert.rejects(finishTask({query:async(sql,params)=> {
    assert.match(sql,/status='running' AND attempts=\?/);assert.equal(params.at(-1),3);return [{affectedRows:0}];
  }},{id:7,attempts:3},'done','created'),/ownership changed/);
});

test('transient GET retries once but ambiguous POST never retries',async()=> {
  const auth={getAccessToken:async()=> 'test-token'};let reads=0,writes=0;
  const got=await requestOkki(auth,'https://example.invalid','/read',undefined,async()=> {
    reads++;if(reads===1)throw Error('timeout');return {ok:true,status:200,json:async()=>({code:200,data:{id:1}})};
  });assert.equal(got.id,1);assert.equal(reads,2);
  await assert.rejects(requestOkki(auth,'https://example.invalid','/write',{id:1},async()=> {writes++;throw Error('timeout');}));
  assert.equal(writes,1);
});

test('outbound number uses Ark invoice verbatim, never OKKI order number',()=> {
  assert.equal(buildPayload({...order,order_no:'OTHER'}, 'ly914首返出库单').serial_id, 'ly914首返出库单');
  assert.throws(()=>buildPayload(order, ''),/Missing Ark invoice/);
});

test('upstream ignoring invoice number is uncertain instead of successful',async t=> {
  let posts=0;
  await assert.rejects(createOne('123',{invoiceNo:'INV123',directory:dir(t),api:async(route,payload)=> {
    if(payload) {posts++;return {outbound_invoice_id:88,serial_id:'UNEXPECTED'};}
    return route.includes('/order/info')?order:{count:0,list:[]};
  }}),e=>e.uncertain===true && /differs/.test(e.message));
  assert.equal(posts,1);
});
