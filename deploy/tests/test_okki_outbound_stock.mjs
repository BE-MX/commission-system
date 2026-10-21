import test from 'node:test';
import assert from 'node:assert/strict';
import {reservationAmounts,protectedStock,assertNoOriginalAttempt,recordNativeAssociation} from '../okki_outbound_stock.mjs';
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
