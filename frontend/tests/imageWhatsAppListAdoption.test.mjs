import test from 'node:test'
import assert from 'node:assert/strict'
import {readFileSync} from 'node:fs'
import * as Vue from 'vue'
import {useAsyncResource} from '../src/composables/useAsyncResource.js'
import {useListPage} from '../src/composables/useListPage.js'
import {clearListResource} from '../src/composables/useListResourceScope.js'
import {useImageSessionList} from '../src/views/design/image-studio/composables/useImageSessionList.js'
import * as imageState from '../src/views/design/image-studio/state.js'
import * as chatState from '../src/views/design/ai-chat/state.js'
import {useChatDrafts} from '../src/views/design/ai-chat/composables/useChatDrafts.js'
import * as admin from '../src/views/customer-image/admin/composables/useCustomerImageAdmin.js'
import {loadComponent,mountComponent,slotShell} from './helpers/mountComponent.mjs'

const deferred=()=>{let resolve,reject;const promise=new Promise((r,j)=>{resolve=r;reject=j});return{promise,resolve,reject}}
const flush=async()=>{await Promise.resolve();await Promise.resolve();await Vue.nextTick();await Promise.resolve()}
const feedback={msgError(){},msgSuccessText(){},msgWarning(){},confirmAction:async()=>{}}
function execute(t,path,result,modules={},props={}) {
 let source=readFileSync(new URL(path,import.meta.url),'utf8');if(path.endsWith('.vue'))source=source.match(/<script setup>([\s\S]*?)<\/script>/)[1]
 source=source.replace(/^import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/gm,(_,binding,key)=>{const b=binding.trim();return b.startsWith('* as ')?`const ${b.slice(5)} = modules[${JSON.stringify(key)}] || {};`:`const ${b.startsWith('{')?b.replace(/\bas\b/g,':'):`{default:${b}}`} = modules[${JSON.stringify(key)}] || {};`}).replace(/export /g,'')
 const auth=Vue.reactive({user:{id:7},roles:[],permissions:[],hasPermission:()=>true})
 const modes={selected:Vue.ref(null),loading:Vue.ref(false),error:Vue.ref(null),locked:Vue.ref(false),restore(){}}
 const defaults={vue:{...Vue,onMounted(){},onBeforeUnmount(){}},'@/stores/auth':{useAuthStore:()=>auth},'@/utils/feedback':feedback,'@/composables/useAsyncResource':{useAsyncResource},'@/composables/useListPage':{useListPage},'@/composables/useListResourceScope':{clearListResource},'@/composables/useTableView':{useTableView:()=>({})},'@/utils/datetime':{formatBeijingDateTime:value=>String(value||'')},'../state':imageState,'./useImageSessionList':{useImageSessionList},'./useAssetObjectUrls':{useAssetObjectUrls:()=>({get(){},cleanup(){},beginBatch(){return 0},load:async()=>{}})},'./useJobPolling':{useJobPolling:()=>({startPolling(){},stopPolling(){}})},'./useChatDrafts':{useChatDrafts},'./useChatModes':{useChatModes:()=>modes},'./composables/useCustomerImageAdmin':admin}
 const scope=Vue.effectScope();t.after(()=>scope.stop());const state=scope.run(()=>new Function('modules','defineProps','defineEmits','sessionStorage',`${source}\nreturn ${result}`)({...defaults,...modules},()=>props,()=>()=>{},{setItem(){},getItem(){},removeItem(){}}))
 return{state,auth}
}
const imageApi=overrides=>({getConfig:async()=>({data:{models:[],remaining_today:0,daily_limit:0}}),getActiveJobs:async()=>({data:{jobs:[]}}),getSession:async id=>({data:{session:{id},messages:[],assets:[],jobs:[]}}),...overrides})

test('image cursor failures retain successful history, retries the same cursor, and duplicate incoming keys merge once',async t=>{
 const queue=[],calls=[];const {state:factory}=execute(t,'../src/views/design/image-studio/composables/useImageStudio.js','useImageStudio',{'@/api/designImage':imageApi({listSessions:(params,config)=>{calls.push({params,config});const item=deferred();queue.push(item);return item.promise}})})
 const state=factory();const initial=state.loadSessions();queue[0].reject(new Error('initial offline'));await initial;assert.equal(state.sessionsResource.errorMessage.value,'initial offline');assert.deepEqual(state.sessions.value,[])
 const retry=state.retrySessions();queue[1].resolve({data:{items:[{id:1,title:'One'}],next_cursor:'real-cursor'}});await retry
 const more=state.loadMoreSessions();assert.deepEqual(calls[2].params,{cursor:'real-cursor'});queue[2].reject(new Error('more offline'));await more;assert.equal(state.sessions.value[0].id,1);assert.equal(state.nextCursor.value,'real-cursor');assert.equal(state.sessionsAppend.value,true)
 const moreRetry=state.retrySessions();assert.deepEqual(calls[3].params,{cursor:'real-cursor'});queue[3].resolve({data:{items:[{id:1,title:'Updated'},{id:2,title:'Earlier'},{id:2,title:'Latest'}],next_cursor:null}});await moreRetry;assert.deepEqual(state.sessions.value.map(row=>row.id),[1,2]);assert.equal(state.sessions.value[1].title,'Latest');assert.equal(state.sessions.value[0].title,'Updated');assert.equal(await state.loadMoreSessions(),false);assert.ok(calls[3].config.signal instanceof AbortSignal)
})

test('image actor switch clears cursor/history and old list response cannot restore private collection',async t=>{
 const queue=[];const {state:factory,auth}=execute(t,'../src/views/design/image-studio/composables/useImageStudio.js','useImageStudio',{'@/api/designImage':imageApi({listSessions:(params,config)=>{const item=deferred();queue.push({...item,config});return item.promise}})})
 const state=factory();const first=state.loadSessions();queue[0].resolve({data:{items:[{id:1}],next_cursor:'old'}});await first;const old=state.loadMoreSessions();auth.user={id:8};await flush();assert.deepEqual(state.sessions.value,[]);assert.equal(state.nextCursor.value,null);assert.equal(queue[1].config.signal.aborted,true)
 queue[2].reject(new Error('new actor offline'));await flush();queue[1].resolve({data:{items:[{id:99}],next_cursor:'late'}});await old;assert.deepEqual(state.sessions.value,[]);assert.equal(state.sessionsResource.errorMessage.value,'new actor offline')
})

test('image pending session creation cannot populate a different actor after successful server write',async t=>{
 const created=deferred();const {state:factory,auth}=execute(t,'../src/views/design/image-studio/composables/useImageStudio.js','useImageStudio',{'@/api/designImage':imageApi({createSession:()=>created.promise,listSessions:async()=>({data:{items:[]}})})})
 const state=factory();const pending=state.newConversation();auth.user={id:8};await flush();created.resolve({data:{id:99,title:'Prior actor'}});await pending;assert.deepEqual(state.sessions.value,[]);assert.equal(state.currentSessionId.value,null)
})

test('chat recent thirty collection retains stale rows and actor switch cancels history plus in-memory drafts',async t=>{
 const queue=[],calls=[];const {state:factory,auth}=execute(t,'../src/views/design/ai-chat/composables/useAiChat.js','useAiChat',{'../state':chatState,'@/api/aiChat':{listSessions:(params,config)=>{calls.push({params,config});const item=deferred();queue.push({...item,config});return item.promise}}})
 const state=factory();const first=state.loadSessions();queue[0].resolve({data:{items:[{id:1}]}});await first;const stale=state.loadSessions();queue[1].reject(new Error('history offline'));await stale;assert.equal(state.sessions.value[0].id,1);assert.equal(state.sessionsResource.errorMessage.value,'history offline');assert.deepEqual(calls[1].params,{limit:30})
 state.prompt.value='private draft';state.newConversation();state.prompt.value='second draft';const old=state.loadSessions();auth.user={id:8};await flush();assert.deepEqual(state.sessions.value,[]);assert.equal(state.prompt.value,'');assert.equal(queue[2].config.signal.aborted,true);queue[3].reject(new Error('actor offline'));await flush();queue[2].resolve({data:{items:[{id:99}]}});await old;state.newConversation();assert.equal(state.prompt.value,'');assert.deepEqual(state.sessions.value,[])
})

const adminFixture=overrides=>({listProducts:async()=>({data:[{id:1,name:'Fixture',cover:null}]}),searchCustomers:async()=>({data:[]}),listInvites:async()=>({data:{items:[],total:0}}),listGenerations:async()=>({data:{items:[],total:0}}),getProductCoverBlob:async()=>({data:new Blob(['fixture'])}),...overrides})
function createAdmin(t,api){const state=admin.createCustomerImageAdminState({api:adminFixture(api)});t.after(state.dispose);return state}

test('customer admin product, invite and usage errors are independent; paged retry preserves exact page/size and stale data page',async t=>{
 let fail=false;const calls=[];const state=createAdmin(t,{listInvites:async(params,config)=>{calls.push({params,config});if(fail)throw new Error('invites offline');return{data:{items:[{id:params.page}],total:100}}},listGenerations:async()=>{throw new Error('usage offline')}})
 await Promise.all([state.loadProducts(),state.loadInvites(2,20),state.loadGenerations()]);assert.equal(state.products.value[0].id,1);assert.equal(state.invites.value[0].id,2);assert.equal(state.generationsResource.errorMessage.value,'usage offline');fail=true;await state.loadInvites(3,50);assert.equal(state.invitesResource.dataPage.value,2);assert.equal(state.invites.value[0].id,2);assert.equal(state.invitesResource.errorMessage.value,'invites offline');await state.invitesResource.fetchList();assert.deepEqual(calls.at(-1).params,{page:3,page_size:50});assert.ok(calls.at(-1).config.signal instanceof AbortSignal)
})

test('customer admin invite create goes to page one and independent read failure keeps one-time plaintext URL',async t=>{
 let fail=false;const calls=[];const state=createAdmin(t,{listInvites:async(params)=>{calls.push(params);if(fail)throw new Error('reread offline');return{data:{items:[{id:1}],total:100}}},createInvite:async()=>({data:{invite_url:'https://fixture.test/create/once'}})})
 await state.loadInvites(3,50);fail=true;await state.submitInvite({customer_id:'C1',product_ids:[1],expires_at:'2099-01-01T00:00:00Z',quota_total:1});assert.equal(state.invitePage.value,1);assert.equal(calls.at(-1).page,1);assert.equal(state.oneTimeInviteUrl.value,'https://fixture.test/create/once');assert.equal(state.invitesResource.errorMessage.value,'reread offline')
})

test('customer admin scope clear cancels independent resources and a late invitation write cannot disclose prior actor URL',async t=>{
 const queue=[],created=deferred();const state=createAdmin(t,{listProducts:(params,config)=>{const item=deferred();queue.push({...item,config});return item.promise},createInvite:()=>created.promise})
 const read=state.loadProducts();const write=state.submitInvite({customer_id:'C1',product_ids:[1],expires_at:'2099-01-01T00:00:00Z',quota_total:1});state.clearScope();assert.equal(queue[0].config.signal.aborted,true);queue[0].resolve({data:[{id:99}]});created.resolve({data:{invite_url:'https://fixture.test/prior-actor'}});await Promise.all([read,write]);assert.deepEqual(state.products.value,[]);assert.equal(state.oneTimeInviteUrl.value,'');assert.equal(state.invitePage.value,1)
})

test('customer admin covers fail/retry separately and changed cover/cleared scope rejects late blob URL creation',async()=>{
 const queue=[],created=[],revoked=[];const covers=admin.createProductCoverController({fetchCover:(id,config)=>{const item=deferred();queue.push({...item,id,config});return item.promise},urlApi:{createObjectURL:blob=>{created.push(blob);return `blob:${blob}`},revokeObjectURL:url=>revoked.push(url)}})
 const first=covers.sync([{id:1,cover:{id:11}}]);queue[0].reject(new Error('cover offline'));await first;assert.match(covers.errors.value[1],/封面读取失败/)
 const retry=covers.sync([{id:1,cover:{id:11}}]);queue[1].resolve({data:'current'});await retry;assert.equal(covers.urls.value[1],'blob:current');const old=covers.sync([{id:1,cover:{id:12}}]);covers.clear();assert.equal(queue[2].config.signal.aborted,true);queue[2].resolve({data:'late'});await old;assert.deepEqual(created,['current']);assert.deepEqual(revoked,['blob:current']);assert.deepEqual(covers.urls.value,{})
})

test('customer admin local revoke result aborts an earlier paged read that could overwrite successful write',async t=>{
 const old=deferred();let calls=0;const state=createAdmin(t,{listInvites:async()=>{calls++;return calls===1?{data:{items:[{id:1}],total:1}}:old.promise},revokeInvite:async()=>({data:{id:1,revoked_at:'fixture'}})})
 await state.loadInvites();const pending=state.loadInvites();await state.revokeInvite(1);old.resolve({data:{items:[{id:1}],total:1}});await pending;assert.equal(state.invites.value[0].revoked_at,'fixture')
})

test('customer editor asset and copy-library reads are independently retryable, scoped and retain successful read on error',async t=>{
 const queue=[];let fail=false;const props=Vue.reactive({modelValue:true,product:{id:1},adminState:{scopeVersion:Vue.ref(0)}})
 const {state}=execute(t,'../src/views/customer-image/admin/ProductTemplateEditor.vue','{resetDraft,loadAssets,assets,assetsResource,openLibrary,loadLibrary,libraryResource,libraryAssets,draft,handleClosed}',{'@/api/customerImage':{listProductAssets:(id,config)=>{const item=deferred();queue.push({...item,id,config});return item.promise},listLibraryAssets:async()=>{if(fail)throw new Error('library offline');return{data:{items:[{id:9}]}}}}},props)
 const first=state.resetDraft();queue[0].resolve({data:[]});await first;await state.openLibrary('reference',1);assert.equal(state.libraryAssets.value[0].id,9);fail=true;await state.loadLibrary();assert.equal(state.libraryAssets.value[0].id,9);assert.equal(state.libraryResource.errorMessage.value,'library offline')
 const late=state.loadAssets();state.handleClosed();assert.equal(queue[1].config.signal.aborted,true);queue[1].resolve({data:[{id:99}]});await late;assert.deepEqual(state.assets.value,[]);assert.deepEqual(state.libraryAssets.value,[])
})

function whatsapp(t,api){return execute(t,'../src/views/system/WhatsAppConnector.vue','{loadAccounts,selectAccount,loadConversations,selectConversation,loadMessages,accountsResource,conversationsResource,messagesResource,accounts,conversations,messages,selectedAccount,selectedConversation,conversationTotal,messageTotal,handlePull}',{'@/api/whatsapp':api})}

test('WhatsApp account and conversation scope change clears old rows, preserves first-failure retry and ignores old account responses',async t=>{
 const queue=[];const {state}=whatsapp(t,{listWhatsAppAccounts:async()=>({data:[{account_uid:'one'},{account_uid:'two'}]}),listWhatsAppConversations:(params,config)=>{const item=deferred();queue.push({...item,params,config});return item.promise},listWhatsAppMessages:async()=>({data:{items:[{message_uid:'one'}],total:72}})})
 await state.loadAccounts();const first=state.selectAccount(state.accounts.value[0]);queue[0].resolve({data:{items:[{conversation_uid:'a'}],total:80}});await first;assert.equal(state.messageTotal.value,72)
 const old=state.loadConversations();const switched=state.selectAccount(state.accounts.value[1]);assert.deepEqual(state.conversations.value,[]);assert.deepEqual(state.messages.value,[]);assert.equal(queue[1].config.signal.aborted,true);queue[2].reject(new Error('two offline'));await switched;queue[1].resolve({data:{items:[{conversation_uid:'late'}],total:99}});await old;assert.deepEqual(state.conversations.value,[]);assert.equal(state.conversationsResource.errorMessage.value,'two offline')
 const retry=state.loadConversations();assert.deepEqual(queue[3].params,{account_uid:'two',page:1,page_size:50});queue[3].resolve({data:{items:[],total:0}});await retry;assert.equal(state.conversationsResource.isEmpty.value,true)
})

test('WhatsApp message changes clear previous thread and retry exact account/conversation bound, preserving stale successful messages',async t=>{
 const queue=[];const {state}=whatsapp(t,{listWhatsAppMessages:(params,config)=>{const item=deferred();queue.push({...item,params,config});return item.promise}})
 state.selectedAccount.value={account_uid:'account'};const first=state.selectConversation({conversation_uid:'one'});queue[0].resolve({data:{items:[{message_uid:'old'}],total:90}});await first;const older=state.loadMessages();const switched=state.selectConversation({conversation_uid:'two'});assert.deepEqual(state.messages.value,[]);queue[2].resolve({data:{items:[{message_uid:'current'}],total:80}});await switched;queue[1].resolve({data:{items:[{message_uid:'late'}],total:99}});await older;assert.equal(state.messages.value[0].message_uid,'current');assert.equal(state.messageTotal.value,80)
 const retry=state.loadMessages();queue[3].reject(new Error('messages offline'));await retry;assert.equal(state.messages.value[0].message_uid,'current');assert.equal(state.messagesResource.errorMessage.value,'messages offline');assert.deepEqual(queue[3].params,{account_uid:'account',conversation_uid:'two',page:1,page_size:50})
})

test('WhatsApp successful sync remains successful when independent account/conversation reread fails',async t=>{
 const notices=[];const {state}=execute(t,'../src/views/system/WhatsAppConnector.vue','{handlePull,accountsResource,conversationsResource,selectedAccount}',{'@/utils/feedback':{...feedback,msgSuccessText:text=>notices.push(text)},'@/api/whatsapp':{pullWhatsAppResource:async()=>({data:{pulled:2}}),listWhatsAppAccounts:async()=>{throw new Error('accounts offline')},listWhatsAppConversations:async()=>{throw new Error('conversations offline')}}})
 state.selectedAccount.value={account_uid:'a'};await state.handlePull(state.selectedAccount.value,'messages');assert.deepEqual(notices,['同步完成：2 条']);assert.equal(state.accountsResource.errorMessage.value,'accounts offline');assert.equal(state.conversationsResource.errorMessage.value,'conversations offline')
})

const status=loadComponent('../../src/components/ListPageStatus.vue',{'@element-plus/icons-vue':{Refresh:{}},'./GlassButton.vue':{default:{emits:['click'],setup:(_,ctx)=>()=>Vue.h('button',{onClick:()=>ctx.emit('click')},ctx.slots.default?.())}}})
test('mounted chat history first failure shows retry, bounded history label and no false empty; stale rows remain visible',async t=>{
 let retries=0;const component=loadComponent('../../src/views/design/ai-chat/components/ChatSidebar.vue',{'@/components/ListPageStatus.vue':{default:status},'@element-plus/icons-vue':{ChatLineRound:slotShell,Plus:slotShell}})
 const props=Vue.reactive({sessions:[],hasLoaded:false,error:'fixture offline',loading:false,canWrite:true,onRetry:()=>retries++})
 const mounted=mountComponent(t,component,props,undefined,{DetailDrawer:slotShell,'el-alert':slotShell});assert.match(mounted.text(),/fixture offline/);assert.match(mounted.text(),/最多 30 条/);assert.doesNotMatch(mounted.text(),/还没有会话/);mounted.find(node=>node.type==='button'&&node.props.onClick).at(-1).props.onClick();assert.equal(retries,1)
 props.sessions=[{id:1,title:'Retained fixture'}];props.hasLoaded=true;await flush();assert.match(mounted.text(),/Retained fixture/);assert.match(mounted.text(),/可能已过期/)
})


test('actual read API wrappers forward cancellation and silent errors without changing query bounds',async t=>{
 const calls=[];const client={get:(path,config)=>{calls.push({path,config});return Promise.resolve({data:[]})}}
 const signal=new AbortController().signal;const config={signal,suppressToast:true};const clients={'./clients':{designImageClient:client,aiChatClient:client,customerImageClient:client,whatsappClient:client}}
 const image=execute(t,'../src/api/designImage.js','{listSessions}',clients).state
 const chat=execute(t,'../src/api/aiChat.js','{listSessions}',clients).state
 const customer=execute(t,'../src/api/customerImage.js','{listProducts,listProductAssets,getProductCoverBlob,listLibraryAssets,searchCustomers,listInvites,listGenerations}',clients).state
 const whatsappApi=execute(t,'../src/api/whatsapp.js','{listWhatsAppAccounts,listWhatsAppConversations,listWhatsAppMessages}',clients).state
 await image.listSessions({cursor:'fixture-cursor'},config);await chat.listSessions({limit:30},config)
 await customer.listProducts({},config);await customer.listProductAssets(1,config);await customer.getProductCoverBlob(1,config);await customer.listLibraryAssets(config);await customer.searchCustomers({search:'fixture'},config);await customer.listInvites({page:2,page_size:20},config);await customer.listGenerations({page:3,page_size:50},config)
 await whatsappApi.listWhatsAppAccounts(config);await whatsappApi.listWhatsAppConversations({account_uid:'a',page:1,page_size:50},config);await whatsappApi.listWhatsAppMessages({account_uid:'a',conversation_uid:'c',page:1,page_size:50},config)
 assert.equal(calls.length,12);for(const call of calls){assert.equal(call.config.signal,signal);assert.equal(call.config.suppressToast,true)}
 assert.deepEqual(calls[0].config.params,{cursor:'fixture-cursor'});assert.deepEqual(calls[1].config.params,{limit:30});assert.deepEqual(calls[11].config.params,{account_uid:'a',conversation_uid:'c',page:1,page_size:50});assert.equal(calls[4].config.responseType,'blob')
})
