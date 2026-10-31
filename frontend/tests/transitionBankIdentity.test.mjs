import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { bankDomainAccounts, legacyBankReconciliationPayload } from '../src/views/commerce-transition/transitionBank.js'

test('canonical bank domain binds all selected numeric account aliases independently of mutable code', () => {
  const accounts = [{ id: 4, code: 'OLD' }, { id: 7, code: 'ALIAS', active: false }]
  assert.deepEqual(bankDomainAccounts([4, 7], accounts), [4, 7])
  accounts[0].code = 'RENAMED'
  assert.deepEqual(bankDomainAccounts([4, 7], accounts), [4, 7])
  for (const ids of [[], [4, 4], [4, 9], [0], [9007199254740993]]) assert.throws(() => bankDomainAccounts(ids, accounts))
})

test('legacy statement reconciliation selects exactly one complete original money ledger without principal inputs', () => {
  const domains = [{ id: 2 }], unmapped = ['legacy-receipt:41', 'legacy-batch:8']
  const form = { domain_id: 2, transaction_id: ' BANK-ORIGINAL-12 ', statement_reference: ' Approved bank statement row 12 ', amount: 999, receipt_id: 999, batch_id: 999 }
  assert.deepEqual(legacyBankReconciliationPayload({ ...form, source: unmapped[0] }, unmapped, domains), {
    domain_id: 2, transaction_id: 'BANK-ORIGINAL-12', statement_reference: 'Approved bank statement row 12', receipt_id: 41,
  })
  assert.deepEqual(legacyBankReconciliationPayload({ ...form, source: unmapped[1] }, unmapped, domains), {
    domain_id: 2, transaction_id: 'BANK-ORIGINAL-12', statement_reference: 'Approved bank statement row 12', batch_id: 8,
  })
})

test('stale source, invented identity, missing bank evidence and unavailable domain all fail before POST', () => {
  const domains = [{ id: 2 }], unmapped = ['legacy-batch:8']
  const form = { domain_id: 2, source: unmapped[0], transaction_id: 'TXN-12', statement_reference: 'Statement row 12' }
  for (const patch of [{ source: 'legacy-receipt:8' }, { source: 'legacy-batch:0' }, { source: 'legacy-batch:8:partial' },
    { source: 'legacy-batch:9007199254740993' }, { domain_id: 3 }, { transaction_id: ' ' }, { statement_reference: '' }]) {
    assert.throws(() => legacyBankReconciliationPayload({ ...form, ...patch }, unmapped, domains))
  }
  assert.throws(() => legacyBankReconciliationPayload(form, [], domains))
})

test('settings uses real writers endpoint, admin authority and read cancellation; late confirmations cannot write another resource', () => {
  const source = readFileSync(new URL('../src/views/commerce-transition/TransitionSettings.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(source, /status\.data\.value\?\.writers/)
  assert.match(source, /getTransitionResource\(resource/)
  assert.match(source, /auth\.hasPermission\('commerce_transition:admin'\)/)
  assert.match(source, /auth\.hasPermission\('receipt:admin'\)/)
  assert.match(source, /bank-identities\/reconcile-legacy/)
  assert.match(source, /current!==generation/)
  assert.match(source, /choices\.cancel\(\)/)
})

function settingsHarness({ permissions = ['commerce_transition:admin', 'receipt:admin'], confirm = async () => {} } = {}) {
  const events = { reads: [], writes: [], messages: [], deactivate: [] }
  const ref = value => ({ value }), computed = getter => ({ get value() { return getter() } })
  function asyncResource(loader) {
    const data=ref(null), error=ref(null), loading=ref(false)
    return { data,error,loading,errorMessage:ref(''),hasData:computed(()=>data.value!==null),cancel(){},clear(){data.value=null},
      async load(){data.value=await loader(null,{signal:new AbortController().signal});return true} }
  }
  function listPage(loader) {
    return {list:ref([]),loading:ref(false),errorMessage:ref(''),hasData:ref(false),cancel(){},
      async fetchList(){return loader(null,{signal:new AbortController().signal,isCurrent:()=>true})} }
  }
  const command = () => ({pending:ref(false),failure:ref(''),reset(){},async run({payload,confirm,send}) {
    try {const body=payload();await confirm();const result=await send(body);return {ok:true,data:result.data}}
    catch(error){return {ok:false,error}}
  }})
  const source = readFileSync(new URL('../src/views/commerce-transition/TransitionSettings.vue', import.meta.url), 'utf8')
    .split('<script setup>')[1].split('</script>')[0].replace(/^import .*\r?\n/gm,'')
  const names = ['ref','computed','onActivated','onDeactivated','useAuthStore','useAsyncResource','useListPage','useNativeCommand',
    'getTransitionStatus','getTransitionResource','getFinanceReference','bankDomainAccounts','legacyBankReconciliationPayload','msgSuccess','confirmAction']
  const values = [ref,computed,()=>{},fn=>events.deactivate.push(fn),()=>({hasPermission:p=>permissions.includes(p)}),asyncResource,listPage,command,
    async()=>({data:{phase:'transition',version:3}}),async resource=>{events.reads.push(resource);return {data:resource==='bank-identities'?{items:[],unmapped_legacy_money:['legacy-batch:8']}:[]}},
    async()=>({data:{accounts:[{id:4,name:'Bank',code:'CODE',currency:'USD'}]}}),bankDomainAccounts,legacyBankReconciliationPayload,
    message=>events.messages.push(message),confirm]
  names.push('saveTransitionResource');values.push(async(resource,body)=>{events.writes.push({resource,body});return {data:{}}})
  const page=new Function(...names,`${source};return {tab,form,choices,unmapped,openEdit,changeTab,save,editOpen}`)(...values)
  return {page,events}
}

test('actual settings controller fetches writers and blocks a confirmed command after KeepAlive deactivation', async () => {
  let release
  const {page,events}=settingsHarness({confirm:()=>new Promise(resolve=>{release=resolve})})
  page.tab.value='writers';page.changeTab();await Promise.resolve()
  assert.deepEqual(events.reads,['writers'])
  page.tab.value='bank-identities';page.changeTab();await Promise.resolve()
  page.openEdit();await page.choices.load()
  page.choices.data.value={domains:[{id:2}]}
  page.form.value={source:'legacy-batch:8',domain_id:2,transaction_id:'TXN',statement_reference:'Bank statement original'}
  const save=page.save();await Promise.resolve()
  events.deactivate.forEach(fn=>fn());release();await save
  assert.deepEqual(events.writes,[]);assert.deepEqual(events.messages,[])
})

test('actual settings controller denies bank reconciliation without receipt admin', () => {
  const {page,events}=settingsHarness({permissions:['commerce_transition:admin']})
  page.tab.value='bank-identities';page.openEdit()
  assert.equal(page.editOpen.value,false)
  assert.deepEqual(events.writes,[])
})


for (const [source_kind, cash_movement] of [['return-paid', 'paid'], ['return-recovered', 'recovered']]) {
  test(`legacy return ${cash_movement} selects one original cash movement without supplying an amount`, () => {
    const form = { source_kind, sales_return_id: 81, domain_id: 2, transaction_id: ' BANK-81 ',
      statement_reference: ' Statement page 3 row 9 ', amount: 999, receipt_id: 41, batch_id: 8,
      source: 'legacy-receipt:41', cash_movement: 'invented' }
    const sources = [`legacy-return-${cash_movement}:81`]
    assert.deepEqual(legacyBankReconciliationPayload(form, sources, [{ id: 2 }]), {
      domain_id: 2, transaction_id: 'BANK-81', sales_return_id: 81, cash_movement,
      statement_reference: 'Statement page 3 row 9',
    })
    for (const patch of [{ sales_return_id: 0 }, { sales_return_id: 9007199254740993 },
      { transaction_id: '' }, { statement_reference: '' }, { source_kind: 'return-pending' }]) {
      assert.throws(() => legacyBankReconciliationPayload({ ...form, ...patch }, sources, [{ id: 2 }]))
    }
    assert.throws(() => legacyBankReconciliationPayload(form, ['legacy-receipt:81'], [{ id: 2 }]))
    assert.throws(() => legacyBankReconciliationPayload(form, [], [{ id: 2 }]))
  })
}

test('actual settings controller posts separately verified refund and recovery identities to the existing endpoint', async () => {
  const { page, events } = settingsHarness({ permissions: ['commerce_transition:admin', 'receipt:admin', 'sales_return:admin'] })
  page.tab.value = 'bank-identities'
  for (const cash_movement of ['paid', 'recovered']) {
    page.openEdit(); await page.choices.load()
    page.choices.data.value = { domains: [{ id: 2 }] }
    page.unmapped.value = [`legacy-return-${cash_movement}:81`]
    page.form.value = { source_kind: `return-${cash_movement}`, sales_return_id: 81, domain_id: 2,
      transaction_id: `TXN-${cash_movement}`, statement_reference: `Statement ${cash_movement}` }
    await page.save()
  }
  assert.deepEqual(events.writes.map(row => [row.resource, row.body.sales_return_id, row.body.cash_movement, row.body.transaction_id]), [
    ['bank-identities/reconcile-legacy', 81, 'paid', 'TXN-paid'],
    ['bank-identities/reconcile-legacy', 81, 'recovered', 'TXN-recovered'],
  ])
  assert.ok(events.writes.every(row => !('amount' in row.body) && !('receipt_id' in row.body)))
})

test('actual settings controller rejects return reconciliation without live return authority before posting', async () => {
  const { page, events } = settingsHarness()
  page.tab.value = 'bank-identities'; page.openEdit(); await page.choices.load()
  page.choices.data.value = { domains: [{ id: 2 }] }
  page.unmapped.value = ['legacy-return-paid:81']
  page.form.value = { source_kind: 'return-paid', sales_return_id: 81, domain_id: 2,
    transaction_id: 'PAID', statement_reference: 'Statement original paid row' }
  await page.save()
  assert.deepEqual(events.writes, [])
})
