import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { useTableSort } from '../src/composables/useTableSort.js'
import { clearListResource } from '../src/composables/useListResourceScope.js'
import { errorMessage } from '../src/utils/errors.js'
import { useAssetTagFilters } from '../src/views/asset/composables/useAssetTagFilters.js'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'

const deferred = () => { let resolve, reject; const promise=new Promise((done,fail)=>{resolve=done;reject=fail});return{promise,resolve,reject} }
const flush = async () => { await Promise.resolve();await Promise.resolve();await Vue.nextTick();await Promise.resolve() }
const tableView = () => ({density:Vue.ref('default'),visibleKeys:Vue.ref([]),panelRef:Vue.ref(null)})
const defaultFeedback = {msgError(){},msgWarning(){},msgSuccess(){},msgSuccessText(){},notifyFeedback(){},confirmAction:async()=>{},confirmDanger:async()=>{}}
const authFixture = () => Vue.reactive({user:{id:7,roles:['admin'],permissions:['asset:write']},hasPermission:()=>true,hasAnyPermission:()=>true})
function compileSource(path,modules,result,window={}) {
  let source=readFileSync(new URL(path,import.meta.url),'utf8')
  if(path.endsWith('.vue'))source=source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
  source=source.replace(/^import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/gm,(_,binding,key)=>`const ${binding.trim().startsWith('{')?binding.replace(/\bas\b/g,':'):`{default:${binding}}`} = modules[${JSON.stringify(key)}] || {};`).replace(/export /g,'')
  return new Function('modules','window',`${source}\nreturn ${result}`)(modules,window)
}
function execute(t,path,result,modules={}) {
  const scope=Vue.effectScope();t.after(()=>scope.stop());const auth=authFixture()
  const defaults={vue:{...Vue,onMounted(){},onBeforeUnmount(){}},'../../../utils/errors.js':{errorMessage},'@/utils/feedback':defaultFeedback,'@/stores/auth':{useAuthStore:()=>auth},'@/composables/useListPage':{useListPage},'@/composables/useAsyncResource':{useAsyncResource},'@/composables/useListResourceScope':{clearListResource},'@/composables/useTableSort':{useTableSort},'@/composables/useTableView':{useTableView:tableView},'./composables/useAssetTagFilters':{useAssetTagFilters},'@/composables/useStimulsoft':{useStimulsoft:()=>({})},'vue-router':{useRouter:()=>({push(){}})}}
  defaults['./composables/useWigLibraryTable']={useWigLibraryTable:compileSource('../src/views/expo/composables/useWigLibraryTable.js',defaults,'useWigLibraryTable')}
  defaults['./composables/useAssetDeletion']={useAssetDeletion:compileSource('../src/views/asset/composables/useAssetDeletion.js',{...defaults,...modules},'useAssetDeletion')}
  return {state:scope.run(()=>compileSource(path,{...defaults,...modules},result)),auth}
}

for(const [file,method,fetcher,rows] of [
  ['expo/WigLibrary','getWigs','fetchWigs','wigs'],['expo/HairColorLibrary','getHairColors','fetchColors','colors'],
  ['expo/ScriptLibrary','getScripts','fetchScripts','scripts'],['expo/SceneImages','getScenes','fetchScenes','scenes'],
  ['aftersales/SopManagement','getAfterSalesSopVersions','fetchVersions','versions'],
]) test(`${file} exposes first/stale failure and retry while preserving its complete-array API scope`,async t=>{
  let fail=true;const calls=[];const key=file.startsWith('expo/')?'@/api/expo':'@/api/aftersales'
  const {state}=execute(t,`../src/views/${file}.vue`,`{listResource,${fetcher},${rows}}`,{[key]:{[method]:async(...args)=>{calls.push(args);if(fail)throw new Error('fixture offline');return{data:method==='getAfterSalesSopVersions'?{items:[{id:1}]}:[{id:1}]}}}})
  assert.equal(await state[fetcher](),false);assert.equal(state.listResource.errorMessage.value,'fixture offline')
  fail=false;await state[fetcher]();assert.equal(state[rows].value[0].id,1)
  fail=true;await state[fetcher]();assert.equal(state[rows].value[0].id,1);assert.equal(state.listResource.errorMessage.value,'fixture offline')
  const config=calls.at(-1).at(-1);assert.ok(config.signal instanceof AbortSignal);assert.equal(config.suppressToast,true)
  if(method==='getHairColors')assert.deepEqual(calls.at(-1)[0],{only_active:0})
  if(method==='getScenes')assert.deepEqual(calls.at(-1)[0],{mode:'tryon'})
})

for(const [file,api,fetcher,filtered,field,applied,key,value] of [
  ['WigLibrary','getWigs','fetchWigs','filteredWigs','keyword','appliedKeyword','model_no','Alpha'],
  ['HairColorLibrary','getHairColors','fetchColors','filteredColors','keyword','appliedKeyword','code','Alpha'],
  ['ScriptLibrary','getScripts','fetchScripts','filteredScripts','typeFilter','appliedType','script_type','opener'],
])test(`${file} local filtering submits a snapshot and refresh/reset never submits a draft accidentally`,async t=>{
  const {state}=execute(t,`../src/views/expo/${file}.vue`,`{${field},${applied},${fetcher},${filtered},applySearch,resetFilters}`,{'@/api/expo':{[api]:async()=>({data:[{id:1,[key]:value},{id:2,[key]:'other'}]})}})
  await state[fetcher]();state[field].value=value;assert.equal(state[filtered].value.length,2)
  await state.applySearch();state[field].value='draft';await state[fetcher]();assert.deepEqual(state[filtered].value.map(row=>row.id),[1]);assert.equal(state[applied].value,value)
  await state.resetFilters();assert.equal(state[filtered].value.length,2);assert.equal(state[applied].value,'')
})

test('asset facets submit only clicked tags and committed keyword; paging/sorting retain snapshots and metadata is current',async t=>{
  const calls=[],queue=[]
  const {state}=execute(t,'../src/views/asset/AssetLibrary.vue','{listState,keyword,activeFilters,onKeywordSearch,handleSortChange,availableTagIds,resetFilters,hasSearchIntent}',{'@/api/asset':{getAssetList:(params,config)=>{calls.push({params,config});const item=deferred();queue.push(item);return item.promise}}})
  await state.listState.fetchList();assert.equal(calls.length,0)
  state.keyword.value='applied';const first=state.onKeywordSearch();queue[0].resolve({data:{items:[{id:1}],total:50,available_tag_ids:[1]}});await first
  state.keyword.value='draft';state.activeFilters.family=[2,3];await flush();assert.equal(calls.at(-1).params.keyword,'applied');assert.equal(calls.at(-1).params.tag_filters,'{"family":[2,3]}')
  const page=state.listState.handlePageChange(2);queue[2].resolve({data:{items:[{id:2}],total:50,available_tag_ids:[2]}});await page
  queue[1].resolve({data:{items:[{id:99}],total:99,available_tag_ids:[99]}});await flush();assert.deepEqual([...state.availableTagIds.value],[2]);assert.equal(state.listState.list.value[0].id,2)
  const sort=state.handleSortChange({prop:'file_name',order:'ascending'});assert.equal(calls.at(-1).params.keyword,'applied');assert.equal(calls.at(-1).params.sort_by,'file_name');queue[3].reject(new Error('asset offline'));await sort
  assert.equal(state.listState.list.value[0].id,2);assert.equal(state.listState.errorMessage.value,'asset offline');assert.deepEqual([...state.availableTagIds.value],[2])
  await state.resetFilters();assert.equal(state.hasSearchIntent.value,false);assert.deepEqual(state.listState.list.value,[]);assert.deepEqual([...state.availableTagIds.value],[]);assert.equal(calls.length,4)
})

test('asset delete uses effective last page and successful write survives failed reread',async t=>{
  let deleted=false,fail=false;const notices=[]
  const {state}=execute(t,'../src/views/asset/AssetLibrary.vue','{listState,keyword,onKeywordSearch,handleDelete}',{'@/utils/feedback':{...defaultFeedback,notifyFeedback:(...args)=>notices.push(args)},'@/api/asset':{getAssetList:async()=>{if(fail)throw new Error('reread offline');return{data:{items:[{id:1}],total:deleted?20:21}}},deleteAsset:async()=>{deleted=true}}})
  state.keyword.value='fixture';await state.onKeywordSearch();await state.listState.handlePageChange(2);await state.handleDelete({id:1,file_name:'fixture'});assert.equal(state.listState.page.value,1)
  fail=true;await state.handleDelete({id:1,file_name:'fixture'});assert.deepEqual(notices,[['success','已删除'],['success','已删除']]);assert.equal(state.listState.errorMessage.value,'reread offline')
})

test('favorite folders and items are separate resources; folder switch clears old rows and ignores late results',async t=>{
  const queue=[];let folderFail=false
  const {state}=execute(t,'../src/views/asset/AssetFavorites.vue','{foldersResource,itemsResource,loadFolders,selectFolder,currentFolderId,items}',{'@/api/asset':{getFavoriteFolders:async()=>{if(folderFail)throw new Error('folders offline');return{data:[{id:1},{id:2}]}},getFavoriteItems:()=>{const item=deferred();queue.push(item);return item.promise}}})
  await state.loadFolders();queue[0].resolve({data:[{id:'old'}]});await flush();assert.equal(state.items.value[0].id,'old')
  const second=state.selectFolder(2);assert.deepEqual(state.items.value,[]);queue[1].reject(new Error('second folder offline'));await second;assert.equal(state.itemsResource.errorMessage.value,'second folder offline')
  const old=state.selectFolder(1),latest=state.selectFolder(2);queue[3].resolve({data:[{id:'current'}]});await latest;queue[2].resolve({data:[{id:'late'}]});await old;assert.equal(state.items.value[0].id,'current')
  folderFail=true;await state.loadFolders();assert.equal(state.foldersResource.errorMessage.value,'folders offline');assert.equal(state.items.value[0].id,'current')
})

test('favorite actor switch clears prior folders/items and new folder read errors are retryable',async t=>{
  let fail=false
  const {state,auth}=execute(t,'../src/views/asset/AssetFavorites.vue','{loadFolders,folders,items,foldersResource}',{'@/api/asset':{getFavoriteFolders:async()=>{if(fail)throw new Error('actor offline');return{data:[{id:1}]}},getFavoriteItems:async()=>({data:[{id:1}]})}})
  await state.loadFolders();await flush();assert.equal(state.items.value.length,1);fail=true;auth.user={id:8,roles:[],permissions:[]};await flush();assert.deepEqual(state.folders.value,[]);assert.deepEqual(state.items.value,[]);assert.equal(state.foldersResource.errorMessage.value,'actor offline')
})

test('tag tree scope switches preserve hidden management values and cannot show another scope after failure',async t=>{
  const calls=[],queue=[]
  const {state}=execute(t,'../src/views/asset/TagDimensionManage.vue','{activeScope,dimensionsResource,dimensions,loadData}',{'@/api/asset':{getTagDimensions:(hidden,scope,config)=>{calls.push({hidden,scope,config});const item=deferred();queue.push(item);return item.promise}}})
  const initial=state.dimensionsResource.load('internal');queue[0].resolve({data:[{id:1,is_visible:0,values:[{id:1,parent_value_id:2}]}]});await initial
  state.activeScope.value='customer';assert.deepEqual(state.dimensions.value,[]);queue[1].reject(new Error('customer tags offline'));await flush();assert.equal(state.dimensionsResource.errorMessage.value,'customer tags offline')
  const retry=state.loadData();assert.equal(calls.at(-1).scope,'customer');assert.equal(calls.at(-1).hidden,true);queue[2].resolve({data:[{id:2,is_visible:0,values:[]}]});await retry;assert.equal(state.dimensions.value[0].is_visible,0)
})

test('wig color matrix rejects stale edit context and exposes an independent retry',async t=>{
  const queue=[]
  const {state}=execute(t,'../src/views/expo/WigLibrary.vue','{loadColorMatrix,matrixResource,colorMatrix,openCreate}',{'@/api/expo':{getWigColorImages:()=>{const item=deferred();queue.push(item);return item.promise}}})
  const old=state.loadColorMatrix(1),latest=state.loadColorMatrix(2);queue[1].reject(new Error('matrix offline'));await latest;queue[0].resolve({data:[{hair_color_id:1}]});await old;assert.deepEqual(state.colorMatrix.value,[]);assert.equal(state.matrixResource.errorMessage.value,'matrix offline')
  const retry=state.matrixResource.load();queue[2].resolve({data:[{hair_color_id:2,angle_photos:['fixture.png'],angle_urls:['/fixture.png']}]});await retry;assert.equal(state.colorMatrix.value[0].hair_color_id,2);assert.equal(state.colorMatrix.value[0].photos[0].path,'fixture.png')
  const pending=state.loadColorMatrix(3);state.openCreate();queue[3].resolve({data:[{hair_color_id:3}]});await pending;assert.deepEqual(state.colorMatrix.value,[])
})

test('report templates retain successful collection; versions are request-owned and separately retryable',async t=>{
  let fail=true;const queue=[]
  const {state}=execute(t,'../src/views/report/ReportCenter.vue','{loadTemplates,templatesResource,templates,showVersionHistory,versionsResource,versionList}',{'@/api/reportCenter':{getReportTemplates:async()=>{if(fail)throw new Error('templates offline');return{data:[{report_code:'fixture'}]}},getTemplateVersions:()=>{const item=deferred();queue.push(item);return item.promise}}})
  await state.loadTemplates();assert.equal(state.templatesResource.errorMessage.value,'templates offline');fail=false;await state.loadTemplates();fail=true;await state.loadTemplates();assert.equal(state.templates.value[0].report_code,'fixture')
  const old=state.showVersionHistory({report_code:'old'}),latest=state.showVersionHistory({report_code:'new'});queue[1].resolve({data:[{version:2}]});await latest;queue[0].resolve({data:[{version:1}]});await old;assert.equal(state.versionList.value[0].version,2)
})

test('SOP successful upload is not reclassified as a failed write when collection reread fails',async t=>{
  const success=[]
  const {state}=execute(t,'../src/views/aftersales/SopManagement.vue','{upload,form,selectedFile,dialogVisible,listResource}',{'@/utils/feedback':{...defaultFeedback,msgSuccess:message=>success.push(message)},'@/api/aftersales':{uploadAfterSalesSop:async()=>{},getAfterSalesSopVersions:async()=>{throw new Error('list offline')}}})
  Object.assign(state.form,{version_no:'fixture',effective_date:'2026-10-02',change_summary:'fixture'});state.selectedFile.value={name:'fixture.pdf'};state.dialogVisible.value=true;await state.upload();assert.equal(state.dialogVisible.value,false);assert.deepEqual(success,['上传并解析 SOP']);assert.equal(state.listResource.errorMessage.value,'list offline')
})

test('asset statistics error/retry retains existing top/trend collection and upload dimensions reject old responses',async t=>{
  let fail=false
  const {state}=execute(t,'../src/views/asset/AssetStats.vue','{loadStats,statsResource,stats,maxTrendCount}',{'@/api/asset':{getDownloadStats:async()=>{if(fail)throw new Error('stats offline');return{data:{top_assets:[{id:1}],trend:[{count:4}]}}}}})
  await state.loadStats();fail=true;await state.loadStats();assert.equal(state.stats.value.top_assets[0].id,1);assert.equal(state.maxTrendCount.value,4);assert.equal(state.statsResource.errorMessage.value,'stats offline')
  const queue=[]
  const {state:upload}=execute(t,'../src/views/asset/AssetUpload.vue','{loadDimensions,dimensions,selectedTags}',{'@/api/asset':{getTagDimensions:()=>{const item=deferred();queue.push(item);return item.promise}}})
  const old=upload.loadDimensions(),latest=upload.loadDimensions();queue[1].resolve({data:[{id:2,is_single_select:1}]});await latest;queue[0].resolve({data:[{id:1,is_single_select:0}]});await old;assert.equal(upload.dimensions.value[0].id,2);assert.equal(upload.selectedTags[1],undefined);assert.equal(upload.selectedTags[2],null)
})

test('upload AI suggestions cannot accept tags from the previously selected file and clear cancels the read',async t=>{
  const queue=[]
  const {state}=execute(t,'../src/views/asset/AssetUpload.vue','{selectedFile,triggerAiAnalysis,aiResource,aiSuggestions,clearFile}',{'@/api/asset':{analyzePreview:()=>{const item=deferred();queue.push(item);return item.promise}}})
  state.selectedFile.value={name:'first.pdf'};const old=state.triggerAiAnalysis('first.pdf')
  state.selectedFile.value={name:'second.pdf'};const latest=state.triggerAiAnalysis('second.pdf')
  queue[1].resolve({data:{confidence:0.1,suggestions:[{dimension_id:2}]}});await latest;queue[0].resolve({data:{confidence:0.8,suggestions:[{dimension_id:1}]}});await old;assert.equal(state.aiSuggestions.value[0].dimension_id,2)
  const pending=state.triggerAiAnalysis('second.pdf');state.clearFile();queue[2].resolve({data:{confidence:0.8,suggestions:[{dimension_id:3}]}});await pending;assert.deepEqual(state.aiSuggestions.value,[]);assert.equal(state.aiResource.error.value,null)
})

test('folder job polling ignores an old job and a closed drawer; its existing three-failure retry preserves job identity',async t=>{
  const queue=[],scheduled=[];let uploaded=0
  t.mock.method(globalThis,'setTimeout',callback=>{scheduled.push(callback);return scheduled.length})
  t.mock.method(globalThis,'clearTimeout',()=>{})
  t.mock.method(console,'warn',()=>{})
  const {state:factory}=execute(t,'../src/views/asset/composables/useFolderUpload.js','useFolderUpload',{'@/api/asset':{getFolderUploadStatus:(id,config)=>{const item=deferred();queue.push({...item,id,config});return item.promise}}})
  const state=factory({dimensions:Vue.ref([]),canAutoCreate:Vue.ref(false),onUploaded:()=>uploaded++})
  state.jobId.value='old';state.retryPolling();state.jobId.value='current';state.retryPolling()
  assert.equal(queue[0].config.signal.aborted,true);queue[1].resolve({data:{status:'completed',report:{marker:'current'}}});await flush();queue[0].resolve({data:{status:'completed',report:{marker:'old'}}});await flush();assert.equal(state.uploadReport.value.marker,'current');assert.equal(uploaded,1)
  state.retryPolling();queue[2].reject(new Error('offline'));await flush();scheduled.pop()();queue[3].reject(new Error('offline'));await flush();scheduled.pop()();queue[4].reject(new Error('offline'));await flush();assert.equal(state.step.value,'poll_error');assert.equal(state.jobId.value,'current');assert.equal(state.uploadReport.value.marker,'current')
  state.retryPolling();state.close();queue[5].resolve({data:{status:'completed',report:{marker:'closed'}}});await flush();assert.equal(state.uploadReport.value.marker,'current');assert.equal(uploaded,1)
})

test('designer slow startup cannot replace a newer instance for the same template code',async t=>{
  const starts=[],disposed=[]
  const {state}=execute(t,'../src/views/report/ReportCenter.vue','{openDesigner,closeDesigner,designerResource}',{'@/api/reportCenter':{getReportTemplate:async()=>({data:{template_content:'fixture'}}),getReportTemplates:async()=>({data:[]})},'@/composables/useStimulsoft':{useStimulsoft:()=>({createDesigner:()=>{const item=deferred();starts.push(item);return item.promise}})}})
  const first=state.openDesigner({report_code:'same',version:1});await flush();const latest=state.openDesigner({report_code:'same',version:2});await flush()
  starts[1].resolve({dispose:()=>disposed.push('latest')});await latest;starts[0].resolve({dispose:()=>disposed.push('old')});await first;assert.deepEqual(disposed,['old'])
  state.closeDesigner();assert.deepEqual(disposed,['old','latest'])
})

test('folder validation/preview failures retry the same step and reset rejects late metadata',async t=>{
  const validation=[],previews=[]
  const {state:factory}=execute(t,'../src/views/asset/composables/useFolderUpload.js','useFolderUpload',{'@/api/asset':{validateFolderUpload:(_,config)=>{const item=deferred();validation.push({...item,config});return item.promise},previewFolderUpload:()=>{const item=deferred();previews.push(item);return item.promise}}})
  const state=factory({dimensions:Vue.ref([]),canAutoCreate:Vue.ref(false)})
  state.open();state.sourceMode.value='server';state.serverPath.value='fixture-folder'
  const initial=state.startValidation();validation[0].reject(new Error('validation offline'));await initial;assert.equal(state.readError.value,'validation offline');assert.equal(state.step.value,'input')
  const retry=state.retryRead();validation[1].resolve({data:{is_valid:true,matched:[],ambiguous:[],unmatched:[]}});await flush();previews[0].reject(new Error('preview offline'));await retry;assert.equal(state.readError.value,'preview offline');assert.equal(state.step.value,'resolution')
  const previewRetry=state.retryRead();previews[1].resolve({data:{items:[{id:'preview'}]}});await previewRetry;assert.equal(state.previewData.value.items[0].id,'preview');assert.equal(state.step.value,'preview')
  const pending=state.startValidation();state.reset();validation[2].resolve({data:{message:'old validation'}});await pending;assert.equal(validation[2].config.signal.aborted,true);assert.equal(state.validationResult.value,null);assert.equal(state.readError.value,'');assert.equal(state.step.value,'input')
})

test('adopted read APIs forward cancellation and preserve explicit domain params and kiosk behavior',async t=>{
  const calls=[],client={interceptors:{response:{use(){}}},get:async(...args)=>{calls.push(args);return{data:[]}}};const config={signal:new AbortController().signal,suppressToast:true,params:{bad:true}}
  const {state:asset}=execute(t,'../src/api/asset.js','{getAssetList,getTagDimensions,getFavoriteFolders,getFavoriteItems,getDownloadStats,getFolderUploadStatus}',{'./clients':{assetClient:client}})
  for(const [name,args] of [['getAssetList',[{page:2}]],['getTagDimensions',[true,'customer']],['getFavoriteFolders',[]],['getFavoriteItems',[1]],['getDownloadStats',[]],['getFolderUploadStatus',['fixture']]]){await asset[name](...args,config);assert.equal(calls.at(-1).at(-1).signal,config.signal,name)}
  await asset.getTagDimensions(true,'customer',config);assert.deepEqual(calls.at(-1)[1].params,{include_hidden:1,scope:'customer'})
  const {state:expo}=execute(t,'../src/api/expo.js','{getWigs,getHairColors,getScripts,getScenes,getWigColorImages}',{'./clients':{expoClient:client},'./expoKioskAuth':{createKioskAuthRecovery:()=>({})}})
  for(const [name,args] of [['getWigs',[{only_active:0}]],['getHairColors',[{only_active:0}]],['getScripts',[{}]],['getScenes',[{mode:'tryon'}]],['getWigColorImages',[1]]]){await expo[name](...args,config);assert.equal(calls.at(-1).at(-1).signal,config.signal,name);if(typeof args[0]==='object')assert.deepEqual(calls.at(-1)[1].params,args[0])}
  await expo.getHairColors({}, {kiosk:true,signal:config.signal});assert.equal(calls.at(-1)[1].suppressToast,true);assert.equal(calls.at(-1)[1].signal,config.signal)
  const {state:report}=execute(t,'../src/api/reportCenter.js','{getReportTemplates,getTemplateVersions,getReportTemplate}',{'./clients':{reportClient:client}})
  for(const [name,args] of [['getReportTemplates',[]],['getTemplateVersions',['fixture']],['getReportTemplate',['fixture']]]){await report[name](...args,config);assert.equal(calls.at(-1).at(-1).signal,config.signal,name)}
})

test('mounted wig library has a usable first-error retry, submitted filter controls and retained successful rows',async t=>{
  let fail=true
  const source=readFileSync(new URL('../src/views/expo/WigLibrary.vue',import.meta.url),'utf8')
  const fixtureVue={...Vue,resolveDirective:()=>({}),createStaticVNode:html=>Vue.h('span',html.replace(/<[^>]*>/g,''))}
  const button={setup:(_,{slots,attrs})=>()=>Vue.h('button',attrs,slots.default?.())}
  const listStatus=loadComponent('../../src/components/ListPageStatus.vue',{'@element-plus/icons-vue':{},'./GlassButton.vue':{default:button}})
  const filterBar=loadComponent('../../src/components/FilterBar.vue',{'@element-plus/icons-vue':{},'./GlassButton.vue':{default:button}})
  const wigTable=compileSource('../src/views/expo/composables/useWigLibraryTable.js',{vue:Vue,'@/composables/useTableView':{useTableView:tableView}},'useWigLibraryTable')
  const component=loadComponent('../../src/views/expo/WigLibrary.vue',{vue:fixtureVue,'@/utils/feedback':defaultFeedback,'@/composables/useAsyncResource':{useAsyncResource},'./composables/useWigLibraryTable':{useWigLibraryTable:wigTable},'@/components/TableTools.vue':{default:{setup:(_,{emit})=>()=>Vue.h('button',{onClick:()=>emit('refresh')},'fixture refresh')}},'@/api/expo':{getWigs:async()=>{if(fail)throw new Error('mounted wigs offline');return{data:[{id:1,name:'Retained wig'}]}}}})
  const registrations=Object.fromEntries([...source.matchAll(/<(el-[a-z-]+)/g)].map(match=>[match[1],slotShell]))
  Object.assign(registrations,{FilterBar:filterBar,ListPageStatus:listStatus,GlassButton:button,DetailDrawer:slotShell,StatusBadge:slotShell,'el-alert':slotShell})
  registrations['el-table']={props:['data'],setup:(props,{slots})=>()=>Vue.h('div',{},props.data.length?props.data.map(row=>Vue.h('p',row.name)):slots.empty?.())}
  const mounted=mountComponent(t,component,{},undefined,registrations);await flush();assert.match(mounted.text(),/mounted wigs offline/);assert.match(mounted.text(),/查询/);assert.match(mounted.text(),/重置/)
  const retry=mounted.find(node=>node.type==='button'&&(node.children||[]).some(child=>child.text==='重试加载'))[0];assert.ok(retry);fail=false;await retry.props.onClick();await flush();assert.match(mounted.text(),/Retained wig/)
  fail=true;mounted.find(node=>node.type==='button'&&node.text==='fixture refresh')[0].props.onClick();await flush();assert.match(mounted.text(),/mounted wigs offline/);assert.match(mounted.text(),/Retained wig/)
})
