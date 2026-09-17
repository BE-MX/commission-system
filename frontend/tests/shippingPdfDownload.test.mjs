import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import { isShippingInspectionPath } from '../src/router/shippingStationRoute.js'
const source = fs.readFileSync(new URL('../src/views/shipping/composables/useInspectionRecords.js', import.meta.url), 'utf8')
  .replace(/^import .*$/gm, '').replace('export function', 'function')
function setup(downloadInspectionPdf) {
  const pushes = [], downloads = [], route = { fullPath: '/shipping/inspections?pdf=42&version=3', query: {pdf:'42',version:'3'} }
  const ctx=vm.createContext({ ref: value=>({value}), reactive: value=>value, computed: fn=>({get value(){return fn()}}),
    useRoute:()=>route, useRouter:()=>({push:async value=>pushes.push(value)}), useListPage:()=>({}),
    downloadInspectionPdf, downloadBlob: value=>downloads.push(value), Blob,
  })
  vm.runInContext(source+';this.s=useInspectionRecords()',ctx)
  return {s:ctx.s,pushes,downloads,route}
}
test('notification route match is exact and never accepts external URLs',()=>{
  assert.equal(isShippingInspectionPath('/shipping/inspections?pdf=42&version=3'),true)
  for(const path of ['/shipping/inspections-other','//evil.test/shipping/inspections','https://evil.test/shipping/inspections'])assert.equal(isShippingInspectionPath(path),false)
})
test('download sends the notification version and restores exact target after expiry',async()=>{
  const calls=[]
  const {s,pushes,route}=setup(async(...args)=>{calls.push(args);throw {response:{status:401}}})
  await s.downloadPdf(s.noticePdf.value)
  assert.deepEqual(calls,[['42','3']])
  assert.equal(pushes[0].query.redirect,route.fullPath)
  assert.equal(s.downloading.value,false)
})
test('stale notification shows the server error and never saves an error blob',async()=>{
  const {s,downloads}=setup(async()=>{throw {response:{status:409,data:new Blob([JSON.stringify({detail:'验货单已撤回或更新'})])}}})
  await s.downloadPdf(s.noticePdf.value)
  assert.equal(s.pdfError.value,'验货单已撤回或更新')
  assert.equal(downloads.length,0)
})
