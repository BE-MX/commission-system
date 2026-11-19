import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import vm from 'node:vm';
import { stripTypeScriptTypes } from 'node:module';
import * as options from '../app/lib/product-options.ts';

async function setup(stock=10) {
 const sql=new DatabaseSync(':memory:');
 const source=readFileSync(new URL('../db/runtime.ts',import.meta.url),'utf8');
 for(const table of ['products','orders','order_items','customer_profiles','sales_people','referrals']) {
   const match=source.match(new RegExp('CREATE TABLE IF NOT EXISTS '+table+' \\([\\s\\S]*?\\n    \\)'));
   assert.ok(match,table);sql.exec(match[0]);
 }
 sql.exec(readFileSync(new URL('../drizzle/0010_loving_selene.sql',import.meta.url),'utf8'));
 sql.prepare(`INSERT INTO products(id,name,length,retail_price,price_a,price_b,stock,created_at,variants) VALUES(1,'测试款','20厘米',9000,7000,6000,?,'2026-11-18',?)`).run(stock,JSON.stringify(options.initialVariants('20厘米')));
 const db={prepare(query){const values=[];const p={bind(...args){values.push(...args);return p;},async first(){return sql.prepare(query).get(...values)??null;},async all(){return {results:sql.prepare(query).all(...values)};},_run(){return {meta:{changes:Number(sql.prepare(query).run(...values).changes)}};},async run(){return p._run();}};return p;},async batch(commands){sql.exec('BEGIN');try{const r=commands.map(x=>x._run());sql.exec('COMMIT');return r;}catch(e){sql.exec('ROLLBACK');throw e;}}};
 const context=vm.createContext({crypto,Response,JSON,Number,String,Array,Date,Set,TextEncoder,Uint8Array});
 const stub=(values)=>new vm.SyntheticModule(Object.keys(values),function(){for(const [k,v]of Object.entries(values))this.setExport(k,v);},{context});
 const imports={
  '../../../db/runtime':stub({getD1:()=>db,ensureDatabase:async()=>{}}),
  '../../lib/admin-auth':stub({requireAdminApi:async()=>null}),
  '../../lib/retail-session':stub({getRetailPhone:async()=> '13900000000'}),
  '../../lib/wholesale-session':stub({getWholesaleAccount:async()=>null}),
  '../../lib/product-options':stub(Object.fromEntries(Object.entries(options))),
  '../../lib/order-items':stub({withOrderItems:async(rows)=>rows}),
 };
 const mod=new vm.SourceTextModule(stripTypeScriptTypes(readFileSync(new URL('../app/api/orders/route.ts',import.meta.url),'utf8')),{context});
 await mod.link(s=>imports[s]);await mod.evaluate();
 const post=(lines,key=crypto.randomUUID(),extra={})=>mod.namespace.POST(new Request('https://shop.test/api/orders',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({mode:'retail',lines,requestId:key,...extra})}));
 return {sql,post};
}
const line=(key='cap0-20',quantity=1)=>({id:1,variantKey:key,quantity});
test('checkout saves the selected cap/length and ignores client-supplied price',async()=>{
 const {sql,post}=await setup();const r=await post([{...line('cap1-20',2),price:1}]);assert.equal(r.status,201);assert.equal((await r.json()).amount,3596);
 const saved=sql.prepare('SELECT * FROM order_items').get();assert.equal(saved.variant_label,'递针前顶 · 20厘米');assert.equal(saved.unit_price,1798);assert.equal(sql.prepare('SELECT stock FROM products').get().stock,8);
});
test('a retry of the same checkout returns the same order and does not deduct stock twice',async()=>{
 const {sql,post}=await setup();const key=crypto.randomUUID();const [a,b]=await Promise.all([post([line()],key),post([line()],key)]);
 assert.ok([200,201].includes(a.status));assert.ok([200,201].includes(b.status));assert.equal((await a.json()).orderNo,(await b.json()).orderNo);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM orders').get().n,1);assert.equal(sql.prepare('SELECT stock FROM products').get().stock,9);
 assert.equal((await post([line('cap1-20')],key)).status,409);
});
test('racing orders cannot oversell stock and a failed batch leaves no partial order',async()=>{
 const {sql,post}=await setup(3);const responses=await Promise.all([post([line('cap0-20',2)]),post([line('cap1-20',2)])]);
 assert.deepEqual(responses.map(r=>r.status).sort(),[201,409]);assert.equal(sql.prepare('SELECT stock FROM products').get().stock,1);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM orders').get().n,1);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM order_items').get().n,1);
});
test('tampered lengths, unpriced variants and over-permission purchases are rejected',async()=>{
 const {sql,post}=await setup();assert.equal((await post([line('cap0-40')])).status,409);
 sql.exec("UPDATE products SET min_level='b'");assert.equal((await post([line()])).status,409);assert.equal(sql.prepare('SELECT COUNT(*) AS n FROM orders').get().n,0);
});
