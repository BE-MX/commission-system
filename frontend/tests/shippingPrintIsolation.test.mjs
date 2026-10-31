import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
const deferred = () => { let resolve; const promise = new Promise(done => { resolve = done }); return { promise, resolve } }
const flush = async () => { for(let n=0;n<6;n++) { await Vue.nextTick(); await Promise.resolve() } }
function harness(t) {
 const props = Vue.reactive({visible:true,recordId:17,mode:'outbound'}), auth = Vue.reactive({user:{id:1,permissions:['shipping_inspection:read']}}), calls=[], emits=[]
 const source=readFileSync(new URL('../src/views/shipping/print/ShippingPrintDialog.vue',import.meta.url),'utf8').match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import .*\r?\n/gm,'')
 const scope=Vue.effectScope();t.after(()=>scope.stop())
 const names=['computed','ref','watch','onDeactivated','onUnmounted','useAuthStore','defineProps','defineEmits','getOutboundPrintData']
 const api=scope.run(()=>new Function(...names,`${source}; return {payload,frameRef,loading,loadError,doPrint,close}`)(Vue.computed,Vue.ref,Vue.watch,()=>{},()=>{},()=>auth,()=>props,()=> (...args)=>emits.push(args),(id,config)=>{const request=deferred();calls.push({id,config,...request});return request.promise}))
 return {api,props,auth,calls,emits}
}
const snapshot = label => ({data:{record:{label},items:[]}})

test('late print-data response after object switch cannot replace the new source snapshot',async t=>{
 const h=harness(t)
 h.props.recordId=18;await flush()
 assert.equal(h.calls[0].config.signal.aborted,true)
 h.calls[1].resolve(snapshot('new-local'));await flush()
 h.calls[0].resolve(snapshot('old-legacy'));await flush()
 assert.equal(h.api.payload.value.record.label,'new-local')
})

test('closing or live permission revocation invalidates a pending print and clears private payload',async t=>{
 const h=harness(t);let prints=0
 h.api.frameRef.value={contentWindow:{focus(){},print(){prints++}}}
 h.calls[0].resolve(snapshot('current'));await flush()
 const printing=h.api.doPrint();assert.equal(h.calls.length,2)
 h.auth.user.permissions=[];await flush()
 h.calls[1].resolve(snapshot('current'));await printing
 assert.equal(prints,0)
 assert.equal(h.api.payload.value,null)
 assert.deepEqual(h.emits.at(-1),['update:visible',false])
})
