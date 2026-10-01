import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { useTableSort } from '../src/composables/useTableSort.js'
import { designActorScope, watchDesignActor } from '../src/views/design/designListScope.js'
import * as status from '../src/views/design/designStatus.js'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'

const deferred = () => { let resolve, reject; const promise = new Promise((done, fail) => { resolve=done;reject=fail });return {promise,resolve,reject} }
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Vue.nextTick(); await Promise.resolve() }
const feedback = { msgSuccessText() {}, msgWarning() {}, confirmAction: async () => {} }
const tableView = () => ({ visibleKeys: Vue.ref([]), panelRef: Vue.ref(null), density: Vue.ref('default') })
const authFixture = () => {
  const auth = Vue.reactive({ user: { id: 7, roles: ['salesperson'], permissions: ['design:write'] } })
  auth.hasPermission = permission => auth.user?.permissions.includes(permission)
  auth.hasAnyPermission = permissions => permissions.some(auth.hasPermission)
  return auth
}
function execute(t,path,result,modules={},props={}) {
  const scope=Vue.effectScope(); t.after(()=>scope.stop())
  const auth=authFixture()
  const defaults={
    vue: { ...Vue, onMounted() {} }, '@/utils/feedback': feedback,
    '@/views/design/designStatus.js': status, '../designStatus.js': status,
    '@/composables/useListPage': { useListPage: (fn,options)=>useListPage(fn,{...options,immediate:false}) },
    '@/composables/useAsyncResource': {useAsyncResource}, '@/composables/useTableSort': {useTableSort}, '@/composables/useTableView': {useTableView:tableView},
    './designListScope': {designActorScope,watchDesignActor}, '../designListScope': {designActorScope,watchDesignActor},
    '@/stores/auth': {useAuthStore:()=>auth}, '@/utils/dict': {getDictMap: async()=>({}),buildDictLabel:String},
    './customer-media/customerMediaGrouping': {groupMediaByTags:()=>[],filterMediaByTags:()=>[]}, './appointmentContract': {},
  }
  let source=readFileSync(new URL(path,import.meta.url),'utf8')
  if(path.endsWith('.vue'))source=source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  source=source.replace(/^import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/gm,(_,binding,key)=>`const ${binding.trim().startsWith('{')?binding.replace(/\bas\b/g,':'):`{default:${binding}}`} = modules[${JSON.stringify(key)}] || {};`).replace(/export default[^\n]+/g,'').replace(/export /g,'')
  return {state:scope.run(()=>new Function('modules','defineProps','defineEmits','window',`${source}\nreturn ${result};`)( {...defaults,...modules},()=>Vue.reactive(props),()=>()=>{},{innerHeight:900,addEventListener(){},removeEventListener(){}} )),auth}
}

for(const [file,binding] of [['MyRequests.vue','listState'],['AuditQueue.vue','listState']])test(`${file} retries first failure and uses submitted filters through paging, stale refresh and sorting`, async t=>{
  let fail=true;const calls=[]
  const {state}=execute(t,`../src/views/design/${file}`,binding,{'@/api/design':{getRequests:async(params,config)=>{calls.push({params,config});if(fail)throw new Error('fixture unavailable');return{data:{items:[{id:1,salesperson_id:7,salesperson_name:'fixture'}],total:80}}},getAttachments:async()=>({data:[]})}})
  assert.equal(await state.fetchList(),false);assert.equal(state.errorMessage.value,'fixture unavailable')
  fail=false;if(file==='MyRequests.vue')state.searchForm.keyword='submitted';await state.handleSearch()
  if(file==='MyRequests.vue')state.searchForm.keyword='draft';await state.handlePageChange(2)
  if(file==='MyRequests.vue')assert.equal(calls.at(-1).params.keyword,'submitted')
  assert.ok(calls.at(-1).config.signal instanceof AbortSignal);assert.equal(calls.at(-1).config.suppressToast,true)
  fail=true;await state.fetchList();assert.equal(state.list.value[0].id,1);assert.equal(state.isStale.value,true)
})

test('self-only scope overrides editable salesperson; authority changes clear rows and retain applied query while keeping draft',async t=>{
  let fail=false;const calls=[]
  const {state,auth}=execute(t,'../src/views/design/MyRequests.vue','{ listState, salespersonOptions }',{'@/api/design':{getRequests:async params=>{calls.push(params);if(fail)throw new Error('new actor unavailable');return{data:{items:[{id:1,salesperson_id:7,salesperson_name:'old actor'}],total:1}}}}})
  state.listState.searchForm.salesperson_id=99;state.listState.searchForm.keyword='applied';await state.listState.handleSearch();assert.equal(calls[0].salesperson_id,7)
  state.listState.searchForm.keyword='draft';fail=true;auth.user={id:8,roles:['salesperson'],permissions:['design:write']};await flush()
  assert.deepEqual(state.listState.list.value,[]);assert.deepEqual(state.salespersonOptions.value,[]);assert.equal(calls.at(-1).salesperson_id,8);assert.equal(calls.at(-1).keyword,'applied');assert.equal(state.listState.searchForm.keyword,'draft')
})

test('my request attachments and logs ignore stale detail reads and expose independent retry',async t=>{
  const logs=[],attachments=[]
  const {state}=execute(t,'../src/views/design/MyRequests.vue','{ toggleDetail, currentDetail, logsResource, attachmentsResource }',{'@/api/design':{
    getAuditLogs:()=>{const item=deferred();logs.push(item);return item.promise},getAttachments:()=>{const item=deferred();attachments.push(item);return item.promise},
  }})
  const old=state.toggleDetail({id:1}),latest=state.toggleDetail({id:2})
  logs[1].resolve({data:[{id:'new log'}]});attachments[1].reject(new Error('attachments offline'));await latest
  logs[0].resolve({data:[{id:'old log'}]});attachments[0].resolve({data:[{id:'old attachment'}]});await old
  assert.equal(state.currentDetail.value.id,2);assert.equal(state.logsResource.data.value[0].id,'new log');assert.equal(state.attachmentsResource.errorMessage.value,'attachments offline')
  const retry=state.attachmentsResource.load();attachments[2].resolve({data:[{id:'recovered'}]});await retry;assert.equal(state.attachmentsResource.data.value[0].id,'recovered')
})

test('audit stats and attachment counts cannot be overwritten by old page; failed count stays unknown and retryable',async t=>{
  const requests=[],counts=[]
  const {state}=execute(t,'../src/views/design/AuditQueue.vue','{ listState, stats, countsResource, attachmentCount }',{'@/api/design':{
    getRequests:()=>{const item=deferred();requests.push(item);return item.promise},getAttachments:()=>{const item=deferred();counts.push(item);return item.promise},
  }})
  const old=state.listState.fetchList(),latest=state.listState.fetchList()
  requests[1].resolve({data:{items:[{id:2}],total:1,stats:{pending:20}}});await latest
  requests[0].resolve({data:{items:[{id:1}],total:99,stats:{pending:999}}});await old
  counts[0].reject(new Error('count unavailable'));await flush()
  assert.equal(state.stats.pending,20);assert.equal(state.attachmentCount({id:2}),null);assert.equal(state.countsResource.errorMessage.value,'count unavailable')
  const retry=state.countsResource.load();counts[1].resolve({data:[{id:3}]});await retry;assert.equal(state.attachmentCount({id:2}),1)
})

test('three manage tabs retain independent submitted date/filter/sort snapshots and first/stale failures',async t=>{
  const calls=[];let fail=false
  const fetcher=async(params,config)=>{calls.push({params,config});if(fail)throw new Error('task offline');return{data:{items:[{id:params.status}],total:101}}}
  const {state:factory}=execute(t,'../src/views/design/composables/useDesignManage.js','useDesignManage',{'@/api/design':{getRequests:fetcher,getTaskList:fetcher}})
  const state=factory()
  fail=true; await Promise.all([state.fetchPending(),state.fetchScheduled(),state.fetchCompleted()])
  for(const type of ['pending','scheduled','completed']){assert.deepEqual(state[`${type}Data`].value,[]);assert.equal(state[`${type}State`].errorMessage.value,'task offline')}
  fail=false
  state.pendingFilters.salesperson_name='pending salesperson';state.pendingFilters.expectDateRange=['2026-10-01','2026-10-02'];await state.searchPending()
  state.scheduledFilters.salesperson_name='scheduled salesperson';state.scheduledFilters.planDateRange=['2026-11-01','2026-11-02'];await state.searchScheduled()
  state.completedFilters.designer_id=3;await state.searchCompleted()
  state.pendingFilters.salesperson_name='pending draft';state.pendingFilters.expectDateRange=['2020-01-01','2020-01-02'];await state.pendingState.handlePageChange(2)
  assert.equal(calls.at(-1).params.salesperson_name,'pending salesperson');assert.equal(calls.at(-1).params.expect_start_date,'2026-10-01')
  state.scheduledFilters.salesperson_name='scheduled draft';await state.handleScheduledSortChange({prop:'task_no',order:'ascending'})
  assert.equal(calls.at(-1).params.salesperson_name,'scheduled salesperson');assert.equal(calls.at(-1).params.sort_field,'task_no');assert.equal(calls.at(-1).params.plan_end_date,'2026-11-02')
  assert.equal(state.completedState.appliedSearchForm.value.designer_id,3);fail=true;await state.fetchCompleted();assert.equal(state.completedData.value[0].id,'completed');assert.equal(state.completedState.errorMessage.value,'task offline')
})

test('confirmation removes pending last row and creates scheduled at page one; completion refreshes completed',async t=>{
  let confirmed=false;const calls=[]
  const {state:factory}=execute(t,'../src/views/design/composables/useDesignManage.js','useDesignManage',{'@/api/design':{
    getRequests:async params=>{calls.push(params);return{data:{items:[{id:1}],total:confirmed?20:21}}},getTaskList:async params=>{calls.push(params);return{data:{items:[],total:80}}},actionRequest:async()=>{confirmed=true},
  }})
  const state=factory();await state.pendingState.handlePageChange(2);await state.scheduledState.handlePageChange(2)
  state.openConfirmDialog({id:1});Object.assign(state.confirmForm,{designer_id:9,startDate:'2026-10-01',endDate:'2026-10-02'});await state.submitConfirm();await flush()
  assert.equal(state.pendingPage.value,1);assert.equal(state.scheduledPage.value,1)
  await state.handleTaskAction({id:1},'complete');await flush();assert.equal(calls.at(-1).status,'completed');assert.equal(calls.at(-1).page,1)
})

test('manage actor switch clears all existing task tabs and designer collection',async t=>{
  let fail=false
  const fetcher=async()=>{if(fail)throw new Error('scope offline');return{data:{items:[{id:1}],total:1}}}
  const {state:factory,auth}=execute(t,'../src/views/design/composables/useDesignManage.js','useDesignManage',{'@/api/design':{getRequests:fetcher,getTaskList:fetcher,getDesigners:async()=>{if(fail)throw new Error('designers offline');return{data:[{id:1,name:'old actor'}]}}}})
  const state=factory();await Promise.all([state.fetchPending(),state.fetchScheduled(),state.fetchCompleted(),state.fetchDesigners()]);fail=true;auth.user={id:8,roles:['design_staff'],permissions:['design:manage']};await flush()
  for(const type of ['pending','scheduled','completed']){assert.deepEqual(state[`${type}Data`].value,[]);assert.equal(state[`${type}State`].errorMessage.value,'scope offline')}
  assert.deepEqual(state.designerData.value,[]);assert.equal(state.designerResource.errorMessage.value,'designers offline')
})

test('media accounts query has a submitted snapshot; remote customers clear empty search and ignore late results',async t=>{
  const calls=[],queue=[];let fail=true
  const {state}=execute(t,'../src/views/design/CustomerMediaAccounts.vue','{ accountsResource, search, submittedSearch, applySearch, load, customersResource, searchCustomers }',{'@/api/customerMedia':{
    getPortalAccounts:async(term,config)=>{calls.push({term,config});if(fail)throw new Error('accounts offline');return{data:[{id:1}]}},searchMediaCustomers:()=>{const item=deferred();queue.push(item);return item.promise},
  }})
  await state.load();assert.equal(state.accountsResource.errorMessage.value,'accounts offline');fail=false;state.search.value='applied';await state.applySearch();state.search.value='draft';await state.load();assert.equal(calls.at(-1).term,'applied')
  const old=state.searchCustomers('older'),latest=state.searchCustomers('current');queue[1].resolve({data:[{id:2}]});await latest;queue[0].resolve({data:[{id:1}]});await old;assert.equal(state.customersResource.data.value[0].id,2)
  await state.searchCustomers(' ');assert.deepEqual(state.customersResource.data.value,[])
})

test('media review main failure/stale retry and tag context race remain independent',async t=>{
  let fail=true;const queue=[]
  const {state}=execute(t,'../src/views/design/CustomerMediaReview.vue','{ reviewsResource, load, open, current, customerTagsResource }',{'@/api/customerMedia':{
    getMediaReviews:async()=>{if(fail)throw new Error('reviews offline');return{data:[{id:1,assets:[]}]}},getBatchCustomerTags:()=>{const item=deferred();queue.push(item);return item.promise},
  }})
  await state.load();assert.equal(state.reviewsResource.errorMessage.value,'reviews offline');fail=false;await state.load();fail=true;await state.load();assert.equal(state.reviewsResource.data.value[0].id,1)
  const old=state.open({id:1,assets:[]}),latest=state.open({id:2,assets:[]});queue[1].resolve({data:[{tag_value_id:2}]});await latest;queue[0].resolve({data:[{tag_value_id:1}]});await old;assert.equal(state.current.value.id,2);assert.equal(state.customerTagsResource.data.value[0].tag_value_id,2)
})

test('media tag mutation cannot apply old asset metadata to a newly opened review',async t=>{
  const write=deferred()
  const {state}=execute(t,'../src/views/design/CustomerMediaReview.vue','{ open, openTagPicker, saveTags, current }',{'@/api/customerMedia':{getBatchCustomerTags:async()=>({data:[]}),updateMediaAssetTags:()=>write.promise}})
  await state.open({id:1,assets:[{id:10,tags:[]}]});state.openTagPicker(state.current.value.assets[0]);const pending=state.saveTags({tags:[]})
  await state.open({id:2,assets:[{id:20,tags:[]}]});write.resolve({data:{assets:[{id:99,tags:[]}]}});await pending;assert.equal(state.current.value.id,2);assert.equal(state.current.value.assets[0].id,20)
})

test('shared request drawer observes request ID changes while open and guards each independent resource',async t=>{
  const queue=[],props=Vue.reactive({modelValue:false,requestId:null})
  const {state}=execute(t,'../src/components/design/RequestDetailDrawer.vue','{ detailResource, attachmentsResource, logsResource, loadDetail }',{'@/api/design':{
    getRequestDetail:()=>{const item=deferred();queue.push(item);return item.promise},getAttachments:async id=>({data:[{id}]}),getAuditLogs:async id=>({data:[{id}]}),getDesigners:async()=>({data:[]}),
  }},props)
  props.modelValue=true;props.requestId=1;await flush();props.requestId=2;await flush()
  assert.equal(queue.length,2);queue[1].resolve({data:{id:2}});await flush();queue[0].resolve({data:{id:1}});await flush()
  assert.equal(state.detailResource.data.value.id,2);assert.equal(state.attachmentsResource.data.value[0].id,2);assert.equal(state.logsResource.data.value[0].id,2)
  props.modelValue=false;await flush();assert.equal(state.detailResource.data.value,null)
})

test('design read API methods forward signal/config without permitting config to replace query',async t=>{
  const calls=[],client={interceptors:{response:{use(){}}},get:async(...args)=>{calls.push(args);return{data:[]}}}
  const {state:api}=execute(t,'../src/api/design.js','{getRequests,getTaskList,getRequestDetail,getDesigners,getAuditLogs,getAttachments}',{'./clients':{designClient:client}})
  const config={signal:new AbortController().signal,suppressToast:true,params:{bad:true}}
  for(const [name,args] of [['getRequests',[{page:2}]],['getTaskList',[{page:3}]],['getRequestDetail',[1]],['getDesigners',[]],['getAuditLogs',[1]],['getAttachments',[1]]]){await api[name](...args,config);const actual=calls.at(-1).at(-1);assert.equal(actual.signal,config.signal,name);assert.equal(actual.suppressToast,true,name);if(typeof args[0]==='object')assert.equal(actual.params,args[0],name)}
  const {state:media}=execute(t,'../src/api/customerMedia.js','{getMediaReviews,getPortalAccounts,searchMediaCustomers,getBatchCustomerTags,getCustomerTagDimensions}',{'./clients':{customerMediaClient:client}})
  for(const [name,args] of [['getMediaReviews',['pending_review']],['getPortalAccounts',['fixture']],['searchMediaCustomers',['fixture']],['getBatchCustomerTags',[1]],['getCustomerTagDimensions',[]]]){await media[name](...args,config);assert.equal(calls.at(-1).at(-1).signal,config.signal,name);assert.equal(calls.at(-1).at(-1).suppressToast,true,name)}
})

test('mounted media accounts first failure offers retry and failed refresh retains actual fixture rows',async t=>{
  let fail=true
  const listStatus=loadComponent('../../src/components/ListPageStatus.vue',{'@element-plus/icons-vue':{},'./GlassButton.vue':{default:slotShell}})
  const component=loadComponent('../../src/views/design/CustomerMediaAccounts.vue',{
    vue:{...Vue,resolveDirective:()=>({}),createStaticVNode:html=>Vue.h('span',html.replace(/<[^>]*>/g,''))},'@/utils/status':{},'@/utils/feedback':feedback,'@/stores/auth':{useAuthStore:authFixture},'./designListScope':{designActorScope},'./appointmentContract':{},
    '@/composables/useAsyncResource':{useAsyncResource},'@/composables/useTableView':{useTableView:tableView},'@/components/TableTools.vue':{default:{setup:(_,{emit})=>()=>Vue.h('button',{onClick:()=>emit('refresh')},'fixture refresh')}},
    '@/api/customerMedia':{getPortalAccounts:async()=>{if(fail)throw new Error('mounted accounts offline');return{data:[{id:1,customer_name:'Retained account'}]}}},
  })
  const table={props:['data'],setup:(props,{slots})=>()=>Vue.h('div',{},props.data.length?props.data.map(row=>Vue.h('p',row.customer_name)):slots.empty?.())}
  const registrations={FilterBar:slotShell,ListPageStatus:listStatus,GlassButton:slotShell,StatusBadge:slotShell,'el-alert':slotShell,'el-table':table,'el-table-column':slotShell,'el-empty':slotShell,'el-input':slotShell,'el-dialog':slotShell,'el-form':slotShell,'el-form-item':slotShell,'el-select':slotShell,'el-option':slotShell}
  const mounted=mountComponent(t,component,{},undefined,registrations);await flush();assert.match(mounted.text(),/mounted accounts offline/)
  const retry=mounted.find(node=>node.props?.onClick&&/重试加载/.test([node.text,...(node.children||[]).map(child=>child.text)].join('')))[0];assert.ok(retry);fail=false;await retry.props.onClick();await flush();assert.match(mounted.text(),/Retained account/)
  fail=true;mounted.find(node=>node.type==='button'&&node.text==='fixture refresh')[0].props.onClick();await flush();assert.match(mounted.text(),/Retained account/);assert.match(mounted.text(),/mounted accounts offline/)
})

for (const file of ['MyRequests.vue', 'AuditQueue.vue']) test(`mounted ${file} renders first failure inside an empty table and retains rows after refresh failure`, async t => {
  let fail = true
  const source = readFileSync(new URL(`../src/views/design/${file}`, import.meta.url), 'utf8')
  const fixtureVue = { ...Vue, resolveDirective: () => ({}), createStaticVNode: html => Vue.h('span', html.replace(/<[^>]*>/g, '')) }
  const listStatus = loadComponent('../../src/components/ListPageStatus.vue', { '@element-plus/icons-vue': {}, './GlassButton.vue': { default: slotShell } })
  const component = loadComponent(`../../src/views/design/${file}`, {
    vue: fixtureVue, '@/views/design/designStatus.js': status, '@/utils/feedback': feedback,
    '@element-plus/icons-vue': Object.fromEntries(['Search', 'Paperclip', 'Download', 'CircleCheck', 'CircleClose'].map(name => [name, slotShell])),
    '@/composables/useListPage': { useListPage }, '@/composables/useAsyncResource': { useAsyncResource },
    './designListScope': { designActorScope, watchDesignActor }, '@/stores/auth': { useAuthStore: authFixture },
    '@/utils/dict': { getDictMap: async () => ({}), buildDictLabel: String },
    '@/composables/useTableSort': { useTableSort }, '@/composables/useTableView': { useTableView: tableView },
    '@/components/design/RequestDetailDrawer.vue': { default: slotShell },
    '@/components/TableTools.vue': { default: { setup: (_, { emit }) => () => Vue.h('button', { onClick: () => emit('refresh') }, 'fixture refresh') } },
    '@/api/design': {
      getRequests: async () => { if (fail) throw new Error(`${file} mounted offline`); return { data: { items: [{ id: 1, customer_name: 'Retained request', salesperson_id: 7 }], total: 1 } } },
      getAttachments: async () => ({ data: [] }),
    },
  })
  const registrations = Object.fromEntries([...source.matchAll(/<(el-[a-z-]+)/g)].map(match => [match[1], slotShell]))
  Object.assign(registrations, { FilterBar: slotShell, ListPageStatus: listStatus, GlassButton: slotShell, StatusBadge: slotShell, DetailDrawer: slotShell, ResponsiveDescriptions: slotShell, 'el-alert': slotShell })
  registrations['el-table'] = { props: ['data'], setup: (props, { slots }) => () => Vue.h('div', {}, props.data.length ? props.data.map(row => Vue.h('p', row.customer_name)) : slots.empty?.()) }
  const mounted = mountComponent(t, component, {}, undefined, registrations)
  await flush()
  assert.match(mounted.text(), new RegExp(`${file} mounted offline`))
  const retry = mounted.find(node => node.props?.onClick && /重试加载/.test([node.text, ...(node.children || []).map(child => child.text)].join('')))[0]
  assert.ok(retry)
  fail = false; await retry.props.onClick(); await flush()
  assert.match(mounted.text(), /Retained request/)
  fail = true; mounted.find(node => node.type === 'button' && node.text === 'fixture refresh')[0].props.onClick(); await flush()
  assert.match(mounted.text(), /Retained request/)
  assert.match(mounted.text(), new RegExp(`${file} mounted offline`))
})

test('review confirmation refuses a replaced review context', async t => {
  const confirmation = deferred(); const calls = []
  const { state } = execute(t, '../src/views/design/CustomerMediaReview.vue', '{ open, decide }', {
    '@/utils/feedback': { ...feedback, confirmAction: () => confirmation.promise },
    '@/api/customerMedia': { getBatchCustomerTags: async () => ({ data: [] }), reviewMediaBatch: async (...args) => calls.push(args) },
  })
  await state.open({ id: 1, assets: [], lock_version: 1 })
  const pending = state.decide('approve')
  await state.open({ id: 2, assets: [], lock_version: 2 })
  confirmation.resolve(); await pending
  assert.deepEqual(calls, [])
})

for (const [file, binding, method] of [['CustomerMediaAccounts.vue', 'accountsResource', 'getPortalAccounts'], ['CustomerMediaReview.vue', 'reviewsResource', 'getMediaReviews']]) test(`${file} clears the previous actor collection even when the new actor read fails`, async t => {
  let fail = false
  const { state, auth } = execute(t, `../src/views/design/${file}`, `{ resource: ${binding}, load }`, {
    '@/api/customerMedia': { [method]: async () => { if (fail) throw new Error('new actor offline'); return { data: [{ id: 1 }] } }, getCustomerTagDimensions: async () => ({ data: [] }) },
  })
  await state.load(); assert.equal(state.resource.data.value[0].id, 1)
  fail = true; auth.user = { id: 8, roles: ['design_staff'], permissions: ['design:manage'] }; await flush()
  assert.equal(state.resource.data.value, null); assert.equal(state.resource.errorMessage.value, 'new actor offline')
})


