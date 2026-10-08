import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import vm from 'node:vm'
import * as vue from 'vue'

const source = fs.readFileSync(new URL('../src/views/invoice/composables/useInvoiceManagePage.js', import.meta.url), 'utf8')
const deferred = () => { let resolve, reject; const promise = new Promise((a,b) => { resolve=a; reject=b }); return { promise, resolve, reject } }
const denied = status => ({ response: { status } })
async function harness() {
  const auth = vue.reactive({ user: { id: 11 }, accessToken: 'synthetic', roles: ['sales'], permissions: ['invoice:read'] })
  const queues = new Map(), calls = [], effects = { downloads: 0, opens: 0, urls: 0 }
  const api = Object.fromEntries(['deleteInvoice','downloadInvoiceExcel','downloadInvoicePdf','fetchInvoicePrintHtml','getInvoiceSyncLogs','getInvoiceSummary','listInvoices','resolveInvoiceSyncUncertain'].map(name => [name, (...args) => {
    calls.push({ name, args }); const q=queues.get(name); return q?.length ? q.shift().promise : Promise.resolve(name==='getInvoiceSummary' ? { total: 0 } : { items: [], total: 0 })
  }]))
  const context = vm.createContext({ Blob, Date, JSON, Number, String, Array, URL: { createObjectURL() { effects.urls++; return 'blob:synthetic' }, revokeObjectURL() {} }, document: { createElement() { return { click() { effects.downloads++ } } } }, window: { open() { effects.opens++ } }, setTimeout() {} })
  const imports = {
    vue: { ...vue, onMounted() {} },
    'element-plus': { ElMessageBox: {} },
    '@/utils/feedback': { msgSuccess() {}, confirmDanger() {} },
    '@/api/invoice': api,
    './invoiceSyncFlow': { INVOICE_SYNC_OUTCOME: {}, isInvoiceSyncing() {}, validateThenSync() {} },
    './invoiceDateTime': { formatInvoiceDateTime() {} },
    '@/utils/datetime': { currentBeijingDate: () => '2026-10-07' },
    '@/stores/auth': { useAuthStore: () => auth },
  }
  const module = new vm.SourceTextModule(source, { context })
  await module.link(name => { const exports=imports[name]; assert.ok(exports); return new vm.SyntheticModule(Object.keys(exports), function() { for (const [key,value] of Object.entries(exports)) this.setExport(key,value) }, { context }) })
  await module.evaluate()
  const scope=vue.effectScope(), page=scope.run(() => module.namespace.useInvoiceManagePage())
  return { auth, page, calls, effects, stop: () => scope.stop(), wait(name) { const d=deferred(); const q=queues.get(name)||[]; q.push(d); queues.set(name,q); return d } }
}
async function run(fn) { const h=await harness(); try { await fn(h) } finally { h.stop() } }

test('denied list clears cached invoice rows, total and logs', () => run(async h => {
  h.page.invoices.value=[{ id:1 }]; h.page.pagination.total=1; h.page.syncLogs.value=[{ id:1 }]
  const d=h.wait('listInvoices'); const p=h.page.loadInvoices(); d.reject(denied(403)); await assert.rejects(p)
  assert.equal(h.page.invoices.value.length,0); assert.equal(h.page.pagination.total,0); assert.equal(h.page.syncLogs.value.length,0)
}))
test('denied logs clear prior invoice logs and title', () => run(async h => {
  h.page.syncLogs.value=[{ id:1 }]; const d=h.wait('getInvoiceSyncLogs'); const p=h.page.openSyncLogs({id:2,invoice_no:'fixture'}); d.reject(denied(403)); await assert.rejects(p)
  assert.equal(h.page.syncLogs.value.length,0); assert.equal(h.page.syncLogsTitle.value,''); assert.equal(h.page.syncLogsVisible.value,false)
}))
test('older successful list cannot refill after newer denial', () => run(async h => {
  const a=h.wait('listInvoices'), b=h.wait('listInvoices'); const p=h.page.loadInvoices(), q=h.page.loadInvoices(); b.reject(denied(403)); await assert.rejects(q); a.resolve({items:[{id:1}],total:1}); await p
  assert.equal(h.page.invoices.value.length,0); assert.equal(h.page.pagination.total,0)
}))
test('latest list wins when responses arrive out of order', () => run(async h => {
  const a=h.wait('listInvoices'), b=h.wait('listInvoices'); const p=h.page.loadInvoices(), q=h.page.loadInvoices(); b.resolve({items:[{id:2}],total:2}); await q; a.resolve({items:[{id:1}],total:1}); await p
  assert.equal(h.page.invoices.value[0].id,2); assert.equal(h.page.pagination.total,2)
}))
test('latest logs remain bound to their invoice', () => run(async h => {
  const a=h.wait('getInvoiceSyncLogs'), b=h.wait('getInvoiceSyncLogs'); const p=h.page.openSyncLogs({id:1,invoice_no:'first'}), q=h.page.openSyncLogs({id:2,invoice_no:'second'}); b.resolve({items:[{id:2}]}); await q; a.resolve({items:[{id:1}]}); await p
  assert.equal(h.page.syncLogs.value[0].id,2); assert.match(h.page.syncLogsTitle.value,/second/)
}))
test('latest summary range wins', () => run(async h => {
  const a=h.wait('getInvoiceSummary'), b=h.wait('getInvoiceSummary'); const p=h.page.loadSummary(); h.page.summaryDateRange.value=['2026-09-01','2026-09-30']; const q=h.page.loadSummary(); b.resolve({total:2}); await q; a.resolve({total:1}); await p; assert.equal(h.page.summary.value.total,2)
}))
for (const [label,apiName,start,read,result] of [
  ['list','listInvoices', h => h.page.loadInvoices(), h => h.page.invoices.value[0]?.id, {items:[{id:2}],total:2}],
  ['summary','getInvoiceSummary', h => h.page.loadSummary(), h => h.page.summary.value?.total, {total:2}],
  ['logs','getInvoiceSyncLogs', h => h.page.openSyncLogs({id:2,invoice_no:'current'}), h => h.page.syncLogs.value[0]?.id, {items:[{id:2}]}],
]) {
  test(`older ${label} denial cannot clear newer successful response`, () => run(async h => {
    const a=h.wait(apiName), b=h.wait(apiName); const p=start(h), q=start(h); b.resolve(result); await q; a.reject(denied(403)); await p.catch(() => {}); assert.equal(read(h),2)
  }))
}
test('role change immediately clears private read views', () => run(async h => {
  h.page.invoices.value=[{id:1}]; h.page.summary.value={total:1}; h.page.syncLogs.value=[{id:1}]; h.auth.permissions=[]
  assert.equal(h.page.invoices.value.length,0); assert.equal(h.page.summary.value,null); assert.equal(h.page.syncLogs.value.length,0)
}))
test('identity change drops pending invoice response', () => run(async h => {
  const d=h.wait('listInvoices'); const p=h.page.loadInvoices(); h.auth.user={id:12}; d.resolve({items:[{id:1}],total:1}); await p; assert.equal(h.page.invoices.value.length,0)
}))
for (const [command,apiName] of [['excel','downloadInvoiceExcel'],['pdf','downloadInvoicePdf'],['print','fetchInvoicePrintHtml']]) {
  test(`${command} response after disposal creates no download or window`, () => run(async h => {
    const d=h.wait(apiName); const p=h.page.handleExport(command,{id:1}); h.stop(); h.auth.user={id:12}; d.resolve(command==='print' ? '<html></html>' : {data:'fixture',headers:{'content-type':'application/octet-stream'}}); await p
    assert.equal(h.effects.downloads,0); assert.equal(h.effects.opens,0); assert.equal(h.effects.urls,0)
  }))
}
test('logout and new login drops pending print without unmount', () => run(async h => {
  const d=h.wait('fetchInvoicePrintHtml'); const p=h.page.handleExport('print',{id:1}); h.auth.accessToken=null; h.auth.user={id:12}; h.auth.accessToken='synthetic-new'; d.resolve('<html></html>'); await p; assert.equal(h.effects.opens,0)
}))
test('current reader can list and export normally', () => run(async h => {
  const d=h.wait('listInvoices'); const p=h.page.loadInvoices(); d.resolve({items:[{id:1}],total:1}); await p; assert.equal(h.page.invoices.value.length,1)
  const f=h.wait('downloadInvoiceExcel'); const q=h.page.handleExport('excel',{id:1}); f.resolve({data:'fixture',headers:{'content-type':'application/octet-stream'}}); await q; assert.equal(h.effects.downloads,1)
  const r=h.wait('fetchInvoicePrintHtml'); const s=h.page.handleExport('print',{id:1}); r.resolve('<html></html>'); await s; assert.equal(h.effects.opens,1)
}))
