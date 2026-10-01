import test from 'node:test'
import assert from 'node:assert/strict'
import * as governanceStatus from '../src/views/governance/governanceStatus.js'
import { viewController } from './helpers/viewController.mjs'

for (const [file,api,method,filters,search] of [
  ['insight/IntelligenceLibrary.vue','insight','listItems','filterForm','handleFilterChange'],
  ['governance/ConceptRegistry.vue','governance','listConcepts','filters','searchConcepts'],
  ['governance/ChangeLog.vue','governance','listChangeLogs','filters','searchLogs'],
]) test(file+' submits filters atomically, retries and retains rows after failure',async t=>{
  const calls=[]; let fails=true, release
  const {vm}=viewController(t,'../../src/views/'+file,`listState,${filters},${search}`,{'./governanceStatus.js':governanceStatus,['@/api/'+api]:{
    [method]:async(params,config)=>{ calls.push(params); assert.ok(config.signal); assert.equal(config.suppressToast,true)
      if(params.keyword==='slow') return new Promise(resolve=>{release=resolve})
      if(fails) throw Error('read failed')
      return {code:200,data:{items:[{id:1,name:'current'}],total:100}}
    },getGovernanceStats:async()=>({data:{}}),
  }})
  await vm.listState.fetchList(); assert.equal(vm.listState.errorMessage.value,'read failed'); assert.equal(vm.listState.isEmpty.value,false)
  fails=false; await vm.listState.fetchList(); assert.equal(vm.listState.list.value[0].name,'current')
  const field= file.endsWith('ChangeLog.vue') ? 'concept_id':'keyword'
  vm[filters][field]='submitted'; await vm[search](); vm[filters][field]='draft'
  await vm.listState.handlePageChange(3); assert.equal(calls.at(-1)[field],'submitted')
  fails=true; await vm.listState.fetchList(); assert.equal(vm.listState.list.value.length,1); assert.equal(vm.listState.isStale.value,true)
  fails=false
  if(field==='keyword') { vm[filters].keyword='slow';const old=vm[search]();vm[filters].keyword='new';await vm[search]();release({data:{items:[{name:'late'}],total:1}});await old;assert.equal(vm.listState.list.value[0].name,'current') }
})

test('intelligence date/multi-select filters and reset sorting use the submitted snapshot',async t=>{
  const calls=[]
  const {vm}=viewController(t,'../../src/views/insight/IntelligenceLibrary.vue','listState,filterForm,handleFilterChange,resetFilter,handleSortChange',{
    '@/api/insight':{listItems:async params=>{calls.push(params);return {data:{items:[],total:0}}}},
  })
  Object.assign(vm.filterForm,{dateRange:['2026-09-01','2026-09-30'],source_types:['rss','manual'],credibility_labels:['verified'],keyword:'applied'})
  await vm.handleFilterChange();vm.filterForm.dateRange=['2026-10-01','2026-10-02']; vm.filterForm.source_types.push('draft')
  await vm.listState.handlePageChange(2)
  assert.equal(calls.at(-1).start_date,'2026-09-01');assert.equal(calls.at(-1).source_types,'rss,manual');assert.equal(calls.at(-1).credibility_labels,'verified')
  await vm.handleSortChange({prop:'title',order:'ascending'});assert.equal(calls.at(-1).keyword,'applied');assert.equal(calls.at(-1).page,1)
  await vm.resetFilter();assert.equal(calls.at(-1).start_date,undefined);assert.equal(calls.at(-1).keyword,'')
})

for(const [file,resource,method,first,second] of [
  ['SourcesAdminView','sourceResource','listSources',[],[{id:1}]],
  ['IndustryDailyView','reportResource','listReports',{items:[],total:0},{items:[{id:1}],total:1}],
  ['InternalReportsView','reportResource','listReports',{items:[],total:0},{items:[{id:1}],total:1}],
  ['MeetingMinutesView','minutesResource','listMinutes',{items:[],total:0},{items:[{id:1}],total:1}],
])test(file+' reports first and refresh failures with current read guards',async t=>{
  let fails=true,release;let slow=false
  const {vm}=viewController(t,'../../src/views/insight/'+file+'.vue',resource,{'@/api/insight':{
    [method]:async(params,config)=>{assert.ok(config.signal);assert.equal(config.suppressToast,true);if(slow)return new Promise(resolve=>{release=resolve});if(fails)throw Error('offline');return {data:second}},
  }})
  const state=vm[resource];await state.load();assert.equal(state.errorMessage.value,'offline');assert.equal(state.isEmpty.value,false)
  fails=false;await state.load();assert.deepEqual(JSON.parse(JSON.stringify(state.data.value)),second)
  fails=true;await state.load();assert.equal(state.isStale.value,true);assert.deepEqual(JSON.parse(JSON.stringify(state.data.value)),second)
  fails=false;slow=true;const old=state.load();slow=false;await state.load();release({data:first});await old;assert.deepEqual(JSON.parse(JSON.stringify(state.data.value)),second)
})

for(const [file,resource,method]of[['IndustryDailyView','htmlResource','getReportHtml'],['InternalReportsView','htmlResource','getReportHtml'],['MeetingMinutesView','detailResource','getMinutesDetail']])test(file+' selected detail cannot be overwritten by an older response',async t=>{
  let release
  const {vm}=viewController(t,'../../src/views/insight/'+file+'.vue',resource,{'@/api/insight':{
    [method]:async(id,config)=>{assert.ok(config.signal);assert.equal(config.suppressToast,true);if(id===1)return new Promise(resolve=>{release=resolve});return method==='getReportHtml'?'report two':{data:{id}}},
  }})
  const state=vm[resource],old=state.load(1,{clear:true});await state.load(2,{clear:true});release(method==='getReportHtml'?'report one':{data:{id:1}});await old
  assert.deepEqual(JSON.parse(JSON.stringify(state.data.value)),method==='getReportHtml'?'report two':{id:2})
})

test('AI tools preserve a complete catalog if a report read fails and local filters apply only on query',async t=>{
  let fail=false
  const previous=globalThis.localStorage;globalThis.localStorage={getItem:()=>null};t.after(()=>{globalThis.localStorage=previous})
  const {vm}=viewController(t,'../../src/views/insight/AIToolsView.vue','toolsResource,filteredTools,searchQuery,searchTools',{'@/api/insight':{
    listReports:async()=>({data:{items:[{id:1,report_date:'2026-10-01'}]}}),
    getReport:async()=>{if(fail)throw Error('report failed');return {data:{source_data:{grouped:{model:[{title:'Model release'}]}}}}},
  }})
  await vm.toolsResource.load();assert.equal(vm.filteredTools.value.length,1);vm.searchQuery.value='absent';assert.equal(vm.filteredTools.value.length,1)
  vm.searchTools();assert.equal(vm.filteredTools.value.length,0)
  fail=true;await vm.toolsResource.load();assert.equal(vm.toolsResource.data.value.tools.length,1);assert.equal(vm.toolsResource.errorMessage.value,'report failed')
})

test('case library shared paging isolates draft and detail selection, retaining mutation success on read failure',async t=>{
  let fails=false,release;const calls=[]
  const {vm}=viewController(t,'../../src/views/insight/composables/useCaseLibrary.js','useCaseLibrary',{'@/api/insight':{
    listCases:async params=>{calls.push(params);if(fails)throw Error('catalog failed');return {data:{items:[{id:1}],total:100}}},
    getCaseDetail:async id=>{if(id===1)return new Promise(resolve=>{release=resolve});return {data:{id}}},
    manualCreateCase:async()=>{fails=true},
  }})
  const state=vm.useCaseLibrary();await state.reload();state.search.value='submitted';await state.searchCases();state.search.value='draft';await state.handlePageChange(2);assert.equal(calls.at(-1).q,'submitted')
  const old=state.openDetail({id:1});await state.openDetail({id:2});release({data:{id:1}});await old;assert.equal(state.currentCase.value.id,2)
  await state.submitCase();assert.equal(state.formDialogVisible.value,false);assert.equal(state.listState.errorMessage.value,'catalog failed');assert.equal(calls.at(-1).page,1)
})
for (const name of ['IndustryDailyView', 'InternalReportsView']) {
  test(name + ' keeps successful HTML visible after same-report refresh fails', async t => {
    let fail = false
    const { vm } = viewController(t, '../../src/views/insight/' + name + '.vue', 'refreshAll,htmlResource,selectedId,loadHtml', { '@/api/insight': {
      listReports: async () => ({ data: { items: [{ id: 7, report_date: '2026-10-01' }], total: 1 } }),
      getReportHtml: async () => { if (fail) throw Error('html offline'); return '<p>previous complete report</p>' },
    } })
    await vm.refreshAll(); fail = true; await vm.refreshAll()
    assert.equal(vm.htmlResource.data.value, '<p>previous complete report</p>')
    assert.equal(vm.htmlResource.isStale.value, true)
    vm.selectedId.value = 8; await vm.loadHtml()
    assert.equal(vm.htmlResource.data.value, null)
  })
}
