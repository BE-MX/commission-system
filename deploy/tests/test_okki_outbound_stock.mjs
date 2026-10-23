import test from 'node:test';
import assert from 'node:assert/strict';
import {reservationAmounts,protectedStock,assertNoOriginalAttempt,recordNativeAssociation,nativeStockReader} from '../okki_outbound_stock.mjs';
import {stockShortages} from '../okki_outbound_creator.mjs';

test('all successful lines reserve exact SKU totals and deletion rows are skipped',()=>{
  assert.deepEqual([...reservationAmounts([{product_id:1,sku_id:11,count:3},{product_id:1,sku_id:11,count:4},
    {product_id:2,sku_id:22,count:10},{unique_id:9,remove:1}])],[['1:11',7],['2:22',10]]);
  for(const count of [0,-1,'bad',Infinity,1.5]) assert.throws(()=>reservationAmounts([{product_id:1,sku_id:11,count}]));
});

test('live destination stock excludes other pending order reservations',async()=>{
  const api=async()=>({count:1,list:[{sku_id:11,warehouse_id:8193514242746,enable_count:10,disable_flag:0}]});
  const payload={invoice_warehouse_id:8193514242746,record_list:[{product_id:1,sku_id:11,outbound_count:7}]};
  assert.deepEqual(await stockShortages(payload,api,new Map([['1:11',8]])),[{sku_id:'11',required:7,available:2}]);
});

test('protected demand reads successful old generation instead of an edited draft',async()=>{
  const conn={query:async sql=>{
    if(sql.startsWith('SELECT id FROM'))return [[{id:2}]];
    if(sql.includes('LEFT JOIN ark_invoice_sync_logs'))return [[{id:1,invoice_id:1,order_id:'101',sync_status:'not_synced',log_id:10,
      request_digest:JSON.stringify({product_list:[{product_id:1,sku_id:11,count:8}]}),response_body:'{"order_id":"101"}'}]];
    if(sql.startsWith('SELECT payload'))return [[]];
    throw Error('Unexpected fixture SQL');
  }};
  assert.deepEqual([...(await protectedStock(conn,'102'))],[['1:11',8]]);
});

test('legacy never replays unfinished Python attempts, including a late fact after finish',async()=>{
  const start={id:1,scope:'outbound-create-attempt',request_id:'nonce',payload:{}};
  const finish={id:2,scope:'outbound-create-finish',payload:{nonce:'nonce'}};
  const late={id:3,scope:'outbound-create-fact',payload:{nonce:'nonce'}};
  for(const events of [[start],[start,finish,late]])await assert.rejects(()=>assertNoOriginalAttempt({query:async()=>[events]},1));
  await assertNoOriginalAttempt({query:async()=>[[start,finish]]},1);
});

for (const status of ['done','skipped']) test(`native ${status} keeps additional demand until verified`,async()=>{
  let transferred=10,changing=false;
  const conn={query:async sql=>{
    if(sql.startsWith('SELECT id FROM ark_okki'))return [[{id:2}]];
    if(sql.includes('LEFT JOIN ark_invoice_sync_logs'))return [[{id:1,invoice_id:1,order_id:'101',status,sync_status:'synced',
      request_digest:JSON.stringify({product_list:[{product_id:1,sku_id:11,count:15}]}),response_body:'{"order_id":"101"}'}]];
    if(sql.includes("scope='outbound-stock-reservation'"))return [[]];
    if(sql.includes("scope='outbound-invoice-sync'"))return [changing?[{id:1}]:[]];
    if(sql.includes("scope='outbound-stock-native'"))return [[{payload:{order_id:'101',warehouse_id:'8193514242746',
      product_list:[{product_id:1,sku_id:11,count:transferred}]}}]];
    throw Error('Unexpected fixture SQL');
  }};
  assert.deepEqual([...(await protectedStock(conn,'102'))],[['1:11',5]]);
  transferred=15;
  assert.deepEqual([...(await protectedStock(conn,'102'))],[['1:11',0]]);
  changing=true;
  assert.deepEqual([...(await protectedStock(conn,'102'))],[['1:11',15]]);
});

test('native occupation records require exact warehouse and order identities',async()=>{
  const rows=[];const conn={query:async(...args)=>rows.push(args)};
  const detail={invoice_warehouse_info:{id:'8193514242746'},record_list:[
    {order_id:'101',product_id:1,sku_id:11,outbound_count:4}]};
  await recordNativeAssociation(conn,1,'101',detail,'2026-10-21 12:00:00');
  assert.equal(JSON.parse(rows[0][1][2]).product_list[0].count,4);
  await assert.rejects(()=>recordNativeAssociation(conn,1,'102',detail,'2026-10-21 12:00:00'));
  assert.equal(rows.length,1);
});

test('historical done after metadata edit uses live credit, retaining only the uncovered demand',async()=>{
  let amount=10,changing=false,calls=0;
  const conn={query:async sql=>{
    if(sql.startsWith('SELECT id FROM ark_okki'))return [[{id:2}]];
    if(sql.includes('LEFT JOIN ark_invoice_sync_logs'))return [[{id:1,invoice_id:1,order_id:'101',status:'done',sync_status:'synced',generation_completed:0,
      request_digest:JSON.stringify({product_list:[{product_id:1,sku_id:11,count:10}]}),response_body:'{"order_id":"101"}'}]];
    if(sql.includes("scope='outbound-invoice-sync'"))return [changing?[{id:1}]:[]];
    if(sql.startsWith('SELECT payload'))return [[]];
    throw Error('Unexpected fixture SQL');
  }};
  const nativeReader=async()=>{calls++;return new Map([['1:11',amount]]);};
  assert.equal((await protectedStock(conn,'102')).get('1:11'),10);
  assert.equal((await protectedStock(conn,'102',{nativeReader,keys:new Set(['1:11'])})).get('1:11'),0);
  amount=4;assert.equal((await protectedStock(conn,'102',{nativeReader})).get('1:11'),6);
  amount=0;assert.equal((await protectedStock(conn,'102',{nativeReader})).get('1:11'),10);
  const previous=calls;changing=true;
  assert.equal((await protectedStock(conn,'102',{nativeReader})).get('1:11'),10);assert.equal(calls,previous);
  changing=false;
  assert.equal((await protectedStock(conn,'102',{nativeReader,keys:new Set(['2:22'])})).get('1:11'),10);assert.equal(calls,previous);
});

test('native reader requires active-list membership and exact warehouse/order/rows',async()=>{
  let ids=[{outbound_invoice_id:'77'}],active=true;
  const detail={outbound_invoice_id:'77',status:1,create_time:'2026-09-28 08:00:00',
    invoice_warehouse_info:{id:'8193514242746'},record_list:[{outbound_record_id:78,order_id:'101',product_id:1,sku_id:11,outbound_count:4}]};
  const conn={query:async sql=>{assert.match(sql,/^SELECT DISTINCT/);return [ids];}};
  const api=async url=>{
    if(url.includes('/info?'))return {...structuredClone(detail),outbound_invoice_id:new URLSearchParams(url.split('?')[1]).get('outbound_invoice_id')};
    assert.match(url,/time_type=2/);return {count:active?ids.length:0,list:active?ids:[]};
  };
  const read=nativeStockReader(conn,api,'lsordertest');
  assert.equal((await read(1,'101')).get('1:11'),4);
  ids.push({outbound_invoice_id:'88'});assert.equal((await read(1,'101')).get('1:11'),8);
  active=false;assert.equal((await read(1,'101')).size,0);active=true;
  detail.invoice_warehouse_info.id='other';await assert.rejects(()=>read(1,'101'));
  detail.invoice_warehouse_info.id='8193514242746';detail.record_list[0].order_id='102';await assert.rejects(()=>read(1,'101'));
  detail.record_list[0].order_id='101';detail.record_list.push({...detail.record_list[0]});await assert.rejects(()=>read(1,'101'));
  detail.record_list.pop();detail.record_list[0].outbound_count=-1;await assert.rejects(()=>read(1,'101'));
  await assert.rejects(()=>nativeStockReader(conn,async()=>{throw Error('offline');},'lsordertest')(1,'101'));
});
