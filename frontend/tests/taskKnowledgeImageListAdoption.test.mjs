import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import * as taskTree from '../src/views/task/taskTree.js'
import * as taskLabels from '../src/views/task/taskLabels.js'
import * as knowledgeState from '../src/views/knowledge/knowledgeState.js'
import * as knowledgeUi from '../src/views/knowledge/knowledgeUi.js'
import * as imageState from '../src/views/design/image-studio/state.js'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'

const deferred = () => { let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j});return{promise,resolve,reject} }
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Vue.nextTick();await Promise.resolve()}
const feedback={msgError(){},msgSuccess(){},confirmAction:async()=>{},confirmDanger:async()=>{}}
function execute(t,path,result,modules={},props={},emit=()=>{}) {
  let source=readFileSync(new URL(path,import.meta.url),'utf8')
  if(path.endsWith('.vue'))source=source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  source=source.replace(/^import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/gm,(_,binding,key)=>`const ${binding.trim().startsWith('{')?binding.replace(/\bas\b/g,':'):`{default:${binding}}`} = modules[${JSON.stringify(key)}] || {};`).replace(/export /g,'')
  const auth=Vue.reactive({user:{id:7,permissions:[]},roles:['admin'],hasPermission:()=>true,hasAnyPermission:()=>true})
  const defaults={vue:{...Vue,onMounted(){},onBeforeUnmount(){}},'@/composables/useAsyncResource':{useAsyncResource},'@/stores/auth':{useAuthStore:()=>auth},'@/utils/feedback':feedback,'@/utils/datetime':{currentBeijingDate:()=> '2026-10-02'},'../taskTree.js':taskTree,'../taskLabels.js':taskLabels,'./useTaskDialog':{useTaskDialog:()=>({ask:async()=>true})},'./knowledgeState.js':knowledgeState,'./knowledgeUi.js':{...knowledgeUi,readSidebarCollapsed:()=>false,writeSidebarCollapsed(){}},'vue-router':{onBeforeRouteLeave(){}},'../state':imageState}
  const scope=Vue.effectScope();t.after(()=>scope.stop())
  const state=scope.run(()=>new Function('modules','defineProps','defineEmits','window',`${source}\nreturn ${result}`)({...defaults,...modules},()=>props,()=>emit,{}))
  return{state,auth}
}
const treeRows=[{id:1,title:'Parent',priority:'P0',status:'in_progress',children:[{id:2,title:'Needle',priority:'P1',status:'todo',children:[]}]},{id:3,title:'Other',priority:'P2',status:'todo',children:[]}]
function taskApis(overrides={}) {return{listTasks:async()=>({data:treeRows}),getTaskStats:async()=>({data:{in_progress:1}}),listTaskModules:async()=>({data:[]}),getTodayBrief:async()=>({data:null}),listTrash:async()=>({data:[]}),...overrides}}

test('task tree submits local filters, keeps ancestor hierarchy and stale tree; each auxiliary read fails independently',async t=>{
  let fail=false;const calls=[]
  const {state:factory}=execute(t,'../src/views/task/composables/useTaskCenter.js','useTaskCenter',{'@/api/task':taskApis({listTasks:async config=>{calls.push(config);if(fail)throw new Error('tree offline');return{data:treeRows}},getTaskStats:async()=>{throw new Error('stats offline')}})})
  const state=factory();await state.loadAll();assert.equal(state.tree.value.length,2);assert.equal(state.statsResource.errorMessage.value,'stats offline')
  state.filters.q='Needle';assert.equal(state.filteredTree.value.length,2);state.applyFilters();assert.equal(state.filteredTree.value[0].id,1);assert.deepEqual(state.filteredTree.value[0].children.map(row=>row.id),[2])
  state.filters.q='draft';fail=true;await state.refresh();assert.equal(state.filteredTree.value[0].children[0].id,2);assert.equal(state.treeResource.errorMessage.value,'tree offline');assert.ok(calls.at(-1).signal instanceof AbortSignal);assert.equal(calls.at(-1).suppressToast,true)
  state.resetFilters();assert.equal(state.filteredTree.value.length,2)
})

test('task actor switch aborts and clears previous tree, modules, trash, stats and ignores late reads',async t=>{
  const queue=[];const {state:factory,auth}=execute(t,'../src/views/task/composables/useTaskCenter.js','useTaskCenter',{'@/api/task':taskApis({listTasks:config=>{const item=deferred();queue.push({...item,config});return item.promise}})})
  const state=factory();const first=state.refresh();queue[0].resolve({data:treeRows});await first;const old=state.refresh();auth.user={id:8};await flush();assert.deepEqual(state.tree.value,[]);assert.equal(queue[1].config.signal.aborted,true)
  queue[2].reject(new Error('new actor offline'));await flush();queue[1].resolve({data:treeRows});await old;assert.deepEqual(state.tree.value,[]);assert.equal(state.treeResource.errorMessage.value,'new actor offline')
})

test('task successful status write survives failed tree reread and preserves transition payload',async t=>{
  const writes=[],notices=[];const {state:factory}=execute(t,'../src/views/task/composables/useTaskCenter.js','useTaskCenter',{'@/utils/feedback':{...feedback,msgSuccess:message=>notices.push(message)},'@/api/task':taskApis({changeTaskStatus:async(id,payload)=>writes.push({id,payload}),listTasks:async()=>{throw new Error('read offline')}})})
  const state=factory();await state.setStatus(treeRows[0],'done');assert.deepEqual(writes,[{id:1,payload:{status:'done',confirm_open_children:true}}]);assert.equal(notices.length,1);assert.equal(state.treeResource.errorMessage.value,'read offline')
})

function knowledge(t,overrides={},modules={}) {
 const api={get:async(path)=>({data:path==='/libraries'?[{id:1,name:'One',role:'admin'},{id:2,name:'Two',role:'viewer'}]:path.includes('/tree')?[]:{id:11,title:'Fixture'}}),...overrides}
 return execute(t,'../src/views/knowledge/KnowledgeWorkbench.vue','{loadLibraries,loadTree,selectLibrary,selectDocument,reloadDocument,librariesResource,treeResource,documentResource,libraries,tree,document,selectedLibraryId,dirty,runSearch,resetSearch,searchQuery,appliedSearchQuery,searchResource,searchResults,openMembers,retryMembers,membersResource,members,memberLibrary,memberDialog,searchMemberCandidates,candidatesResource,memberCandidates,resetMemberDialog,openApprovals,approvalsResource,inspectApproval,reviewResource,reviewDetail,saveDocument}',{'@/api/clients':{knowledgeClient:api},...modules})
}

test('knowledge library switch respects dirty guard, clears previous tree/document and rejects late library tree',async t=>{
 let allow=false;const queue=[];const {state}=knowledge(t,{get:async path=>{if(path==='/libraries')return{data:[{id:1,role:'admin'},{id:2,role:'viewer'}]};if(path.includes('/tree')){const item=deferred();queue.push({...item,path});return item.promise};return{data:{id:11,title:'Fixture'}}}}, {'@/utils/feedback':{...feedback,confirmAction:async()=>{if(!allow)throw new Error('cancel')}}})
 const first=state.loadLibraries();await flush();queue[0].resolve({data:[{id:1,parent_id:null}]});await first;await state.selectDocument(11);state.dirty.value=true;assert.equal(await state.selectLibrary(2),false);assert.equal(state.selectedLibraryId.value,1);assert.equal(state.document.value.id,11)
 allow=true;const old=state.loadTree();const switched=state.selectLibrary(2);await flush();assert.deepEqual(state.tree.value,[]);assert.equal(state.document.value,null);queue[2].reject(new Error('two offline'));await switched;queue[1].resolve({data:[{id:999}]});await old;assert.deepEqual(state.tree.value,[]);assert.equal(state.treeResource.errorMessage.value,'two offline')
 const retry=state.loadTree();assert.equal(queue[3].path,'/libraries/2/tree');queue[3].resolve({data:[{id:2,parent_id:null}]});await retry;assert.equal(state.tree.value[0].id,2)
})

test('knowledge search retries submitted query instead of draft and preserves bounded limit twenty',async t=>{
 let fail=false;const calls=[];const {state}=knowledge(t,{get:async(path,config)=>{calls.push({path,config});if(fail)throw new Error('search offline');return{data:[{document_id:1}]}}})
 state.searchQuery.value='committed';await state.runSearch();state.searchQuery.value='draft';fail=true;await state.searchResource.load();assert.equal(calls.at(-1).config.params.q,'committed');assert.equal(calls.at(-1).config.params.limit,20);assert.equal(state.searchResults.value[0].document_id,1);assert.equal(state.searchResource.errorMessage.value,'search offline')
 state.resetSearch();assert.deepEqual(state.searchResults.value,[]);assert.equal(state.appliedSearchQuery.value,'')
})

test('knowledge member list opens on first error, cannot receive another library and closing cancels candidate reads',async t=>{
 const queue=[];const {state}=knowledge(t,{get:(path,config)=>{const item=deferred();queue.push({...item,path,config});return item.promise}})
 const old=state.openMembers({id:1}),latest=state.openMembers({id:2});assert.equal(state.memberDialog.value,true);queue[1].reject(new Error('members offline'));await latest;queue[0].resolve({data:[{user_id:99}]});await old;assert.deepEqual(state.members.value,[]);assert.equal(state.membersResource.errorMessage.value,'members offline')
 const retry=state.retryMembers();assert.equal(queue[2].path,'/libraries/2/members');queue[2].resolve({data:[{user_id:2,role:'admin'}]});await retry;assert.equal(state.members.value[0].user_id,2)
 const search=state.searchMemberCandidates('member');state.resetMemberDialog();assert.equal(queue[3].config.signal.aborted,true);queue[3].resolve({data:[{user_id:9}]});await search;assert.deepEqual(state.memberCandidates.value,[])
})

test('knowledge repeated candidate query preserves successful matches on failure; different query clears prior matches',async t=>{
 let fail=false;const {state}=knowledge(t,{get:async()=>{if(fail)throw new Error('candidate offline');return{data:[{user_id:1}]}}})
 state.memberLibrary.value={id:1};await state.searchMemberCandidates('same');fail=true;await state.searchMemberCandidates('same');assert.equal(state.memberCandidates.value[0].user_id,1);assert.equal(state.candidatesResource.isStale.value,true)
 await state.searchMemberCandidates('different');assert.deepEqual(state.memberCandidates.value,[]);assert.equal(state.candidatesResource.errorMessage.value,'candidate offline')
})

test('knowledge save acknowledges successful write even when tree reread fails, preserves editor callback and current metadata',async t=>{
 let done=0,failed=0;const {state}=knowledge(t,{get:async()=>{throw new Error('tree offline')},put:async()=>({data:{id:41,version_no:2}})})
 state.selectedLibraryId.value=1;state.document.value={id:11,title:'Old'};await state.saveDocument({title:'Saved',content:{type:'doc'},done:()=>done++,fail:()=>failed++});assert.equal(done,1);assert.equal(failed,0);assert.equal(state.document.value.title,'Saved');assert.equal(state.document.value.version_no,2);assert.equal(state.treeResource.errorMessage.value,'tree offline')
})

test('knowledge approvals and frozen review have independent first/stale failures and guarded detail identity',async t=>{
 const queue=[];const {state}=knowledge(t,{get:(path,config)=>{const item=deferred();queue.push({...item,path,config});return item.promise}})
 const list=state.openApprovals();queue[0].reject(new Error('approvals offline'));await list;assert.equal(state.approvalsResource.errorMessage.value,'approvals offline')
 const old=state.inspectApproval({id:1}),latest=state.inspectApproval({id:2});queue[2].resolve({data:{id:2,title:'Frozen'}});await latest;queue[1].resolve({data:{id:1,title:'Late'}});await old;assert.equal(state.reviewDetail.value.id,2)
 const retry=state.reviewResource.load();assert.equal(queue[3].path,'/approvals/2');queue[3].reject(new Error('review offline'));await retry;assert.equal(state.reviewDetail.value.id,2);assert.equal(state.reviewResource.errorMessage.value,'review offline')
})

test('reference scope clears rows/selection and guarded thumbnail batch errors are retryable',async t=>{
 const queue=[];let thumbFail=true;const props=Vue.reactive({visible:true,maxUploadMb:20});const {state}=execute(t,'../src/views/design/image-studio/components/ReferenceLibraryDialog.vue','{fetchItems,switchScope,items,selected,listResource,thumbnailResource}',{'@/api/designImage':{listLibraryAssets:(scope,config)=>{const item=deferred();queue.push({...item,scope,config});return item.promise}},'../composables/useLibraryObjectUrls':{useLibraryObjectUrls:()=>({get:()=>null,revokeAll(){},load:async()=>{if(thumbFail)throw new Error('thumbnail offline')}})}},props)
 const first=state.fetchItems();queue[0].resolve({data:{items:[{id:1}]}});await first;await flush();state.selected.value={id:1};assert.equal(state.thumbnailResource.errorMessage.value,'thumbnail offline');thumbFail=false;await state.thumbnailResource.load();assert.equal(state.thumbnailResource.error.value,null)
 const old=state.fetchItems();state.switchScope('private');assert.deepEqual(state.items.value,[]);assert.equal(state.selected.value,null);queue[2].reject(new Error('private offline'));await flush();queue[1].resolve({data:{items:[{id:99}]}});await old;assert.deepEqual(state.items.value,[]);assert.equal(state.listResource.errorMessage.value,'private offline');props.visible=false;await flush();assert.equal(state.listResource.error.value,null)
})

test('reference upload completed after scope switch does not prepend into current scope',async t=>{
 const upload=deferred();let reads=0;const {state}=execute(t,'../src/views/design/image-studio/components/ReferenceLibraryDialog.vue','{doUpload,switchScope,items}',{'@/api/designImage':{uploadLibraryAsset:()=>upload.promise,listLibraryAssets:async()=>{reads++;return{data:{items:[{id:2}]}}}},'../composables/useLibraryObjectUrls':{useLibraryObjectUrls:()=>({get:()=>null,revokeAll(){},load:async()=>{}})}},{visible:true})
 const pending=state.doUpload({name:'fixture.png'});state.switchScope('private');await flush();upload.resolve({data:{id:99}});await pending;assert.deepEqual(state.items.value.map(item=>item.id),[2]);assert.equal(reads,1)
})

test('object URL registry discards closed/superseded blobs and new request for same id remains cached',async t=>{
 const queue=[],created=[],revoked=[];const {state:factory}=execute(t,'../src/views/design/image-studio/composables/useLibraryObjectUrls.js','useLibraryObjectUrls')
 const urls=factory({fetchAsset:(id,config)=>{const item=deferred();queue.push({...item,id,config});return item.promise},urlApi:{createObjectURL:blob=>{created.push(blob);return `blob:${blob}`},revokeObjectURL:url=>revoked.push(url)}})
 const old=urls.load(1);urls.revokeAll();assert.equal(queue[0].config.signal.aborted,true);const latest=urls.load(1);queue[1].resolve({data:'current'});assert.equal(await latest,'blob:current');queue[0].resolve({data:'late'});assert.equal(await old,null);assert.deepEqual(created,['current']);assert.equal(await urls.load(1),'blob:current');urls.revokeAll();assert.deepEqual(revoked,['blob:current'])
})

test('template management uses submitted includeInactive, reset keeps inactive management, successful save survives reread',async t=>{
 const calls=[],notices=[];let fail=false;const {state}=execute(t,'../src/views/design/image-studio/components/PromptTemplateManagerDialog.vue','{fetchItems,applySearch,resetFilters,showInactive,items,listResource,form,save,editing}',{'@/utils/feedback':{...feedback,msgSuccess:message=>notices.push(message)},'@/api/designImage':{listPromptTemplates:async(options,config)=>{calls.push({options,config});if(fail)throw new Error('templates offline');return{data:{items:[{id:1,is_active:false}]}}},createPromptTemplate:async()=>{}}},{visible:true})
 await state.fetchItems();state.showInactive.value=false;await state.fetchItems();assert.equal(calls.at(-1).options.includeInactive,true);await state.applySearch();assert.equal(calls.at(-1).options.includeInactive,false);await state.resetFilters();assert.equal(calls.at(-1).options.includeInactive,true)
 Object.assign(state.form.value,{category:'fixture',name:'Fixture',content:'plain',options:[]});fail=true;await state.save();assert.deepEqual(notices,['保存']);assert.equal(state.editing.value,null);assert.equal(state.listResource.errorMessage.value,'templates offline');assert.equal(state.items.value[0].is_active,false)
})

test('prompt library and pantone are separate complete collections with category navigation and render cap retained',async t=>{
 let fail=false;const {state}=execute(t,'../src/views/design/image-studio/components/PromptLibraryDialog.vue','{fetchTemplates,templates,listResource,ensurePantone,pantoneResource,pantoneColors,pantoneQuery,visiblePantone,pantoneTotal,category,filteredTemplates}',{'@/api/designImage':{listPromptTemplates:async()=>{if(fail)throw new Error('templates offline');return{data:{items:[{id:1,category:'product'},{id:2,category:'scene'}]}}},listPantoneColors:async()=>({data:{items:Array.from({length:300},(_,id)=>({code:String(id),name:'Fixture',hex:'#000000'}))}})}},{visible:true})
 await state.fetchTemplates();state.category.value='scene';assert.equal(state.filteredTemplates.value[0].id,2);fail=true;await state.fetchTemplates();assert.equal(state.templates.value.length,2);assert.equal(state.listResource.errorMessage.value,'templates offline');await state.ensurePantone();assert.equal(state.pantoneTotal.value,300);assert.equal(state.visiblePantone.value.length,240);state.pantoneQuery.value='299';assert.equal(state.visiblePantone.value[0].code,'299')
})

test('task detail scope change clears previous events/form metadata and first failure leaves retry available',async t=>{
 const queue=[],events=[];const props=Vue.reactive({modelValue:true,taskId:1,refreshKey:0,modules:[],tree:[]})
 const {state}=execute(t,'../src/views/task/components/TaskDetailDrawer.vue','{load,detailResource,detail,form}',{'@/api/task':{getTask:(id,config)=>{const item=deferred();queue.push({...item,id,config});return item.promise}}},props,(...args)=>events.push(args))
 const old=state.load();props.taskId=2;await flush();assert.equal(queue[0].config.signal.aborted,true);assert.equal(state.detail.value,null)
 queue[1].reject(new Error('detail offline'));await flush();queue[0].resolve({data:{id:1,title:'Late',acceptance:[]}});await old;assert.equal(state.detail.value,null);assert.deepEqual(events,[]);assert.equal(state.detailResource.errorMessage.value,'detail offline')
 const retry=state.load();queue[2].resolve({data:{id:2,title:'Current',acceptance:['Fixture'],events:[{id:2}]}});await retry;assert.equal(state.form.title,'Current');assert.equal(state.detail.value.events[0].id,2)
 props.modelValue=false;await flush();assert.equal(state.detail.value,null)
})

test('knowledge forced actor change clears prior library permissions/tree/editor and aborts prior document hydration',async t=>{
 let actorChanged=false;const gate=deferred();const {state,auth}=knowledge(t,{get:async path=>{if(actorChanged)throw new Error('actor offline');if(path==='/libraries')return{data:[{id:1,role:'admin'}]};if(path.includes('/tree'))return{data:[{id:11,parent_id:null}]};return gate.promise}})
 await state.loadLibraries();const old=state.selectDocument(11);await flush();actorChanged=true;auth.user={id:8};await flush();assert.deepEqual(state.libraries.value,[]);assert.deepEqual(state.tree.value,[]);assert.equal(state.document.value,null)
 gate.resolve({data:{id:11,title:'Prior actor'}});await old;assert.equal(state.document.value,null);assert.equal(state.librariesResource.errorMessage.value,'actor offline')
})

test('real task/image read API wrappers forward abort/toast config without changing domain parameters',t=>{
 const calls=[],client={get:(...args)=>calls.push(args)};const controller=new AbortController(),config={signal:controller.signal,suppressToast:true}
 const {state:task}=execute(t,'../src/api/task.js','{listTasks,getTask,listTrash,getTaskStats,listTaskModules,getTodayBrief}',{'./clients':{taskClient:client}})
 task.listTasks(config);task.getTask(7,config);task.listTrash(config);task.getTaskStats(config);task.listTaskModules(config);task.getTodayBrief(config)
 assert.deepEqual(calls.map(call=>call[0]),['/items','/items/7','/trash','/stats','/modules','/brief/today']);for(const call of calls){assert.equal(call[1].signal,controller.signal);assert.equal(call[1].suppressToast,true);assert.equal(call[1].showLoading,false)};assert.equal(calls.at(-1)[1].timeout,90000)
 calls.length=0;const {state:image}=execute(t,'../src/api/designImage.js','{listPromptTemplates,listLibraryAssets,listPantoneColors,getLibraryAssetBlob}',{'./clients':{designImageClient:client}})
 image.listPromptTemplates({includeInactive:true},config);image.listLibraryAssets('private',config);image.listPantoneColors(config);image.getLibraryAssetBlob(7,{thumbnail:true,...config})
 assert.deepEqual(calls[0][1].params,{include_inactive:true});assert.deepEqual(calls[1][1].params,{scope:'private'});assert.deepEqual(calls[3][1].params,{thumbnail:true});assert.equal(calls[3][1].responseType,'blob');for(const call of calls)assert.equal(call[1].signal,controller.signal)
})

const status=loadComponent('../../src/components/ListPageStatus.vue',{'@element-plus/icons-vue':{Refresh:{}},'./GlassButton.vue':{default:{emits:['click'],setup:(_,ctx)=>()=>Vue.h('button',{onClick:()=>ctx.emit('click')},ctx.slots.default?.())}}})
const registrations={DetailDrawer:slotShell,ListPageStatus:status,'el-alert':slotShell,'el-empty':{props:['description'],setup:p=>()=>Vue.h('p',p.description)},'el-dialog':slotShell,GlassButton:slotShell}
for(const [name,path,props,extra] of [
 ['approval queue','../../src/views/knowledge/components/ApprovalQueue.vue',{modelValue:true,items:[],readLoaded:false,readError:'fixture offline',readLoading:false},{}],
 ['template manager','../../src/views/design/image-studio/components/PromptTemplateManagerDialog.vue',{visible:true},{'@element-plus/icons-vue':{Close:{},Plus:{}},'@/components/GlassButton.vue':{default:slotShell},'@/api/designImage':{listPromptTemplates:async()=>{throw new Error('fixture offline')}},'@/utils/feedback':feedback,'@/composables/useAsyncResource':{useAsyncResource},'@/stores/auth':{useAuthStore:()=>({user:{id:7}})}}],
])test(`mounted ${name} first failure displays actual retry and no false empty`,async t=>{
 let retries=0;const component=loadComponent(path,{vue:{...Vue,resolveDirective:()=>({})},...extra});const mounted=mountComponent(t,component,{...props,onRetry:()=>retries++},undefined,{...registrations,FilterBar:slotShell,...Object.fromEntries(['el-switch','el-icon','el-select','el-option','el-input','el-input-number'].map(key=>[key,slotShell]))});
 if(name==='template manager'){mounted.find(node=>node.props?.onOpen)[0].props.onOpen();await flush()}
 assert.match(mounted.text(),/fixture offline/);assert.match(mounted.text(),/重试加载/);assert.doesNotMatch(mounted.text(),/没有待审批|还没有模板/)
 const retryButton=mounted.find(node=>node.type==='button'&&node.props?.onClick)[0];assert.ok(retryButton);retryButton.props.onClick();await flush();if(name==='approval queue')assert.equal(retries,1);else assert.match(mounted.text(),/fixture offline/)
})

