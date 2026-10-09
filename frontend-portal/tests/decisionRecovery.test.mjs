import test from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createOrderDecision } from '../src/state/orderDecision.mjs'
import { PortalError } from '../src/api/client.mjs'
const id='11111111-1111-4111-8111-111111111111', rev='22222222-2222-4222-8222-222222222222', account='33333333-3333-4333-8333-333333333333'
const prefix='leshine.portal.action:', hash='a'.repeat(64)
const payloadHash=value=>createHash('sha256').update(JSON.stringify({hash_schema:1,payload:value})).digest('hex')
const storage=()=>{const rows=new Map();return {rows,getItem:k=>rows.get(k)??null,setItem:(k,v)=>rows.set(k,v),removeItem:k=>rows.delete(k)}}
function setup(store=storage(), action='cancel') {
 const calls=[],listeners=new Set(), pi=action.endsWith('_pi')
 const proposal={revision_id:rev,content_hash:hash,expires_at:'2030-01-01T00:00:00',bound_invoice_document_version:3}
 const order={request_id:id,request_no:'PRIVATE-REFERENCE',row_version:'9007199254740993',status:pi?'invoice_created':'awaiting_customer',available_actions:[action],proposal,pi_amendment:{proposal}}
 const original={request_id:id,row_version:'9007199254740994',...(action==='cancel'?{status:'cancelled'}:{revision_id:rev,content_hash:hash,...(pi?{invoice_document_version:3}:{status:action.startsWith('accept')?'ready_for_review':'submitted'})})}
 const receipt={original_receipt:original,current_state:pi?'invoice_created':action==='cancel'?'cancelled':'ready_for_review',row_version:'9007199254740994',...(pi?{amendment_state:'accepted'}:{})}
 const api={session:{me:{account_public_id:account},capabilities:{place_order:true}},subscribe:f=>{listeners.add(f);return()=>listeners.delete(f)},
 async cancel(...args){calls.push(['POST',...args]);assert.ok(store?.getItem(prefix+account));throw new PortalError('LOST','Unknown',{uncertain:true})},
 async decide(...args){calls.push(['POST',...args]);throw new PortalError('LOST','Unknown',{uncertain:true})},
 async order(){calls.push(['GET status']);return order},
 async actionReceipt(request,locator){calls.push(['GET receipt',request,locator]);return {found:true,command:{request_id:request,...locator},receipt}}}
 const controller=createOrderDecision({api,storage:store,now:()=>Date.parse('2026-10-01T00:00:00+08:00')})
 return {store,calls,api,controller,order,receipt,listeners,clear(){api.session=null;listeners.forEach(f=>f({reason:'another-tab'}))}}
}
for(const action of ['cancel','reject_proposal','accept_proposal','reject_pi','accept_pi']) test(action+' refresh recovers exact receipt via GET without reconstructing POST',async()=>{
 const c=setup(storage(),action), reason='私密地址\nLondon 😀'
 await c.controller.begin(c.order,action,reason)
 const raw=c.store.getItem(prefix+account),marker=JSON.parse(raw)
 assert.equal(marker.payload_hash,payloadHash(action.startsWith('accept')?{proposal_hash:hash}:{reason}))
 for(const text of [reason,'PRIVATE-REFERENCE','value','account_public_id']) assert.ok(!raw.includes(text))
 assert.equal(marker.version,'9007199254740993');assert.equal(marker.request_id,id)
 c.controller.dispose(); const restored=createOrderDecision({api:c.api,storage:c.store})
 assert.equal(restored.restorePending(),true);assert.equal(restored.state.status,'uncertain');assert.equal(restored.state.canRetry,false)
 assert.throws(()=>restored.retry(),{code:'ACTION_UNAVAILABLE'})
 const posts=c.calls.filter(x=>x[0]==='POST').length
 assert.equal((await restored.recover()).status,'confirmed');assert.equal(c.calls.filter(x=>x[0]==='POST').length,posts)
 assert.equal(c.store.getItem(prefix+account),null);assert.equal(restored.state.operation.value,undefined)
})
test('missing original receipt remains unknown even when current status resembles success',async()=>{
 const c=setup();await c.controller.begin(c.order,'cancel','Original reason');c.controller.dispose()
 const restored=createOrderDecision({api:c.api,storage:c.store});restored.restorePending()
 c.api.actionReceipt=async(request,locator)=>({found:false,command:{request_id:request,...locator}})
 c.api.order=async()=>({...c.order,status:'cancelled'})
 assert.equal((await restored.recover()).status,'uncertain');assert.equal(restored.state.latest.status,'cancelled')
 assert.ok(c.store.getItem(prefix+account));assert.throws(()=>restored.begin(c.order,'cancel','New reason'),{code:'ACTION_PENDING'})
})
for(const mutation of [x=>x.command.request_id=rev,x=>x.command.action='accept_pi',x=>x.command.payload_hash='b'.repeat(64),x=>x.receipt.original_receipt.status='submitted',x=>x.found='true']) test('mismatched original query is never confirmation '+mutation.toString(),async()=>{
 const c=setup();await c.controller.begin(c.order,'cancel','Original reason')
 c.api.actionReceipt=async(request,locator)=>{const result={found:true,command:{request_id:request,...locator},receipt:structuredClone(c.receipt)};mutation(result);return result}
 assert.equal((await c.controller.recover()).status,'uncertain');assert.equal(c.controller.state.receipt,undefined);assert.ok(c.store.getItem(prefix+account))
})
for(const raw of ['broken',JSON.stringify({schema:1,request_id:id,action:'cancel',version:'1',payload_hash:hash,reason:'private'}),JSON.stringify({schema:1,request_id:id,action:'cancel',version:true,payload_hash:hash})]) test('corrupt/expanded recovery markers block before POST without exposing content '+raw.slice(0,10),()=>{
 const c=setup();c.store.setItem(prefix+account,raw)
 assert.throws(()=>c.controller.restorePending(),{code:'RECOVERY_RECORD_INVALID'})
 assert.throws(()=>c.controller.begin(c.order,'cancel','Original'),{code:'RECOVERY_RECORD_INVALID'});assert.equal(c.calls.length,0);assert.equal(c.store.getItem(prefix+account),raw)
})
test('unreadable configured storage blocks before dispatch',()=>{
 const c=setup({getItem(){throw Error('PRIVATE')},setItem(){},removeItem(){}})
 assert.throws(()=>c.controller.begin(c.order,'cancel','Original'),{code:'RECOVERY_STORAGE_UNAVAILABLE'});assert.equal(c.calls.length,0)
})
test('late receipt after logout hides data and retains the same-account marker',async()=>{
 const c=setup();await c.controller.begin(c.order,'cancel','Original');let resolve,entered
 const began=new Promise(r=>entered=r);c.api.actionReceipt=()=>new Promise(r=>{resolve=r;entered()})
 const work=c.controller.recover();await began;c.clear();resolve({found:true,command:{request_id:id,action:'cancel',payload_hash:hash},receipt:c.receipt})
 await assert.rejects(work,{code:'STALE_SCOPE',uncertain:true});assert.deepEqual(c.controller.state,{status:'idle'});assert.ok(c.store.getItem(prefix+account))
})
test('late successful cleanup cannot delete a replacement marker',async()=>{
 const c=setup();await c.controller.begin(c.order,'cancel','Original');const original=c.store.getItem(prefix+account)
 c.api.actionReceipt=async(request,locator)=>{c.store.setItem(prefix+account,original.replace('"schema":1','"schema":1 '));return {found:true,command:{request_id:request,...locator},receipt:c.receipt}}
 assert.equal((await c.controller.recover()).status,'confirmed');assert.notEqual(c.store.getItem(prefix+account),null)
})
test('a different account does not restore or remove another account reference',async()=>{
 const c=setup();await c.controller.begin(c.order,'cancel','Original');c.controller.dispose();c.api.session.me.account_public_id=rev
 const restored=createOrderDecision({api:c.api,storage:c.store});assert.equal(restored.restorePending(),false);assert.ok(c.store.getItem(prefix+account))
})

test('reason body and UTF-8 hash match actual Python ReasonInput/content_hash vectors',async()=>{
 const {readFile}=await import('node:fs/promises')
 const vectors=JSON.parse(await readFile(new URL('./decisionReasonVectors.json',import.meta.url),'utf8'))
 for(const vector of vectors){const c=setup();await c.controller.begin(c.order,'cancel',vector.input);assert.equal(c.calls.find(x=>x[0]==='POST').at(-1),vector.reason);assert.equal(JSON.parse(c.store.getItem(prefix+account)).payload_hash,vector.payload_hash)}
})
async function pausedDigest(run){
 const actual=globalThis.crypto;let finish,entered
 const dispatched=new Promise(resolve=>entered=resolve)
 Object.defineProperty(globalThis,'crypto',{configurable:true,value:{subtle:{digest(...args){entered();return new Promise(resolve=>{finish=()=>resolve(actual.subtle.digest(...args))})}}}})
 try{await run(dispatched,()=>finish())}finally{Object.defineProperty(globalThis,'crypto',{configurable:true,value:actual})}
}
test('identity change while preparing hash stops before POST and marker write',async()=>pausedDigest(async(dispatched,finish)=>{
 const c=setup(),work=c.controller.begin(c.order,'cancel','Original');await dispatched;c.clear();finish()
 await assert.rejects(work,{code:'STALE_SCOPE',uncertain:false});assert.deepEqual(c.calls,[]);assert.equal(c.store.rows.size,0)
}))
test('pending reference inserted during hashing is retained and blocks this new POST',async()=>pausedDigest(async(dispatched,finish)=>{
 const c=setup(),work=c.controller.begin(c.order,'cancel','Original');await dispatched
 const raw=JSON.stringify({schema:1,request_id:rev,action:'cancel',version:'1',payload_hash:hash});c.store.setItem(prefix+account,raw);finish()
 assert.equal((await work).status,'failed');assert.equal(c.controller.state.error.code,'ACTION_PENDING');assert.deepEqual(c.calls,[]);assert.equal(c.store.getItem(prefix+account),raw)
}))
for(const mode of ['write-denied','silent-write','readback-denied']) test(mode+' reports memory-only recovery and retains original POST once',async()=>{
 const rows=new Map();let writes=0
 const store={getItem(k){if(mode==='readback-denied'&&writes)throw Error('denied');return rows.get(k)??null},setItem(k,v){writes++;if(mode==='write-denied')throw Error('denied');if(mode!=='silent-write')rows.set(k,v)},removeItem:k=>rows.delete(k)}
 const c=setup(store);c.api.cancel=async(...args)=>{c.calls.push(['POST',...args]);throw new PortalError('LOST','Unknown',{uncertain:true})}
 assert.equal((await c.controller.begin(c.order,'cancel','Original')).status,'uncertain');assert.equal(c.controller.state.refreshRecovery,false);assert.equal(c.calls.filter(x=>x[0]==='POST').length,1);assert.equal(c.controller.state.canRetry,true)
})
test('lone surrogate text fails before POST instead of hashing replacement text',async()=>{
 const c=setup();assert.equal((await c.controller.begin(c.order,'cancel','Reason\ud800')).status,'failed');assert.equal(c.calls.length,0);assert.equal(c.store.rows.size,0)
})
