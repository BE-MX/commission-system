import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createOne,requestOkki} from '../okki_outbound_creator.mjs';
const order={order_id:123,company_id:2,handler:[9],create_time:'2026-09-20 09:00:00',product_list:[{product_id:4,sku_id:5,unique_id:6,count:2,unit_price:10}]};
function directory(t){const d=fs.mkdtempSync(path.join(os.tmpdir(),'outbound-isolation-'));t.after(()=>fs.rmSync(d,{recursive:true,force:true}));return d;}
function apiFor({collision=false,mixed=false,qty=2}={}){
 let posted;
 return async(route,payload)=>{
  if(payload){posted=payload;return {outbound_invoice_id:88,serial_id:payload.serial_id};}
  if(route.includes('/order/info'))return order;
  if(route.includes('/outbound/list'))return {count:0,list:[]};
  if(route.includes('serial_id='))return collision&&!route.includes('%5B123%5D')?{outbound_invoice_id:77,serial_id:'INV',company_info:{id:9},record_list:[{order_id:999}]}:null;
  return {outbound_invoice_id:88,serial_id:posted.serial_id,status:1,company_info:{id:2},remark:'',record_list:[{order_id:123,order_record_id:6,product_id:4,sku_id:5,outbound_count:qty,sale_price:10},...(mixed?[{order_id:999,outbound_count:4}]:[])]};
 };
}
test('historical serial collision uses an order-specific new number',async t=>{
 const result=await createOne('123',{invoiceNo:'INV',directory:directory(t),api:apiFor({collision:true})});
 assert.equal(result.serial_id,'INV [123]');
});
test('upstream mixed order response is quarantined and never recorded as success',async t=>{
 const d=directory(t);
 await assert.rejects(createOne('123',{invoiceNo:'INV',directory:d,api:apiFor({mixed:true})}),e=>e.uncertain===true);
 assert.equal(fs.existsSync(path.join(d,'logs','created-outbound.jsonl')),false);
});
test('upstream wrong quantity is quarantined',async t=>{
 await assert.rejects(createOne('123',{invoiceNo:'INV',directory:directory(t),api:apiFor({qty:3})}),e=>e.uncertain===true);
});
test('only exact serial lookup Not Found Resource proves vacancy',async()=>{
 const auth={getAccessToken:async()=> 'test'};
 const response=async()=>({ok:true,status:200,json:async()=>({code:404,message:'Not Found Resource'})});
 assert.equal(await requestOkki(auth,'','/v1/invoices/outbound/info?serial_id=INV',undefined,response),null);
 await assert.rejects(requestOkki(auth,'','/v1/invoices/order/info?order_id=123',undefined,response));
});

test('both serials occupied stops without submitting',async t=>{
 let posts=0;
 await assert.rejects(createOne('123',{invoiceNo:'INV',directory:directory(t),api:async(route,payload)=>{
  if(payload){posts++;throw Error('unexpected POST');}
  if(route.includes('/order/info'))return order;
  if(route.includes('/outbound/list'))return {count:0,list:[]};
  return {outbound_invoice_id:77,serial_id:new URLSearchParams(route.split('?')[1]).get('serial_id'),record_list:[{order_id:999}]};
 }}),/serial collision/);
 assert.equal(posts,0);
});
test('serial lookup failure never submits',async t=>{
 let posts=0;
 await assert.rejects(createOne('123',{invoiceNo:'INV',directory:directory(t),api:async(route,payload)=>{
  if(payload)posts++;
  if(route.includes('/order/info'))return order;
  if(route.includes('/outbound/list'))return {count:0,list:[]};
  throw Error('serial lookup unavailable');
 }}),/unavailable/);
 assert.equal(posts,0);
});
test('existing mixed document cannot resolve uncertain submission as success',async t=>{
 await assert.rejects(createOne('123',{invoiceNo:'INV',knownIds:['77'],directory:directory(t),api:async(route,payload)=>{
  assert.equal(payload,undefined);
  if(route.includes('/order/info'))return order;
  return {record_list:[{order_id:123},{order_id:999}]};
 }}),e=>e.uncertain===true);
});
test('existing isolated serial is reused without POST',async t=>{
 const result=await createOne('123',{invoiceNo:'INV',directory:directory(t),api:async(route,payload)=>{
  assert.equal(payload,undefined);
  if(route.includes('/order/info'))return order;
  if(route.includes('/outbound/list'))return {count:0,list:[]};
  return {outbound_invoice_id:77,serial_id:'INV',record_list:[{order_id:123}]};
 }});
 assert.equal(result.outcome,'existing');assert.equal(result.outbound_invoice_id,77);
});

test('uncertain wrong quantity remains quarantined on recovery',async t=>{
 const d=directory(t);let created=false,posts=0;
 const base=apiFor({qty:3});
 const api=async(route,payload)=>{
  if(payload){created=true;posts++;}
  if(created&&route.includes('/outbound/list'))return {count:1,list:[{outbound_invoice_id:88,serial_id:'INV'}]};
  return base(route,payload);
 };
 for(let n=0;n<2;n++)await assert.rejects(createOne('123',{invoiceNo:'INV',directory:d,api}),e=>e.uncertain===true);
 assert.equal(posts,1);
});
