import { createApp, ref, h } from 'vue'
import { createPinia } from 'pinia'
import { createRouter, createWebHashHistory } from 'vue-router'
import ElementPlus, { ElForm } from 'element-plus'
import 'element-plus/dist/index.css'
import '../../../src/styles/tokens.css'
import '../../../src/styles/app.css'
import DetailDrawer from '../../../src/components/DetailDrawer.vue'
import AiChat from '../../../src/views/design/ai-chat/AiChat.vue'
import AiPresetChatFields from '../../../src/views/system/components/AiPresetChatFields.vue'
import ChatOperations from '../../../src/views/system/components/ChatOperations.vue'
import { useAuthStore } from '../../../src/stores/auth'
import * as clients from '../../../src/api/clients'

const query = new URLSearchParams(location.search)
const models = [{preset_id: 1, label: '模拟视觉模型', vision: true}, {preset_id: 2, label: '模拟文字模型', vision: false}]
const saved = JSON.parse(sessionStorage.getItem('ai-chat-v2-fixture') || '{}')
const sessions = saved.sessions || []
let nextId = saved.nextId || 1, nextMessage = saved.nextMessage || 100
const store = new Map(saved.store || [])
let limits = saved.limits || {default_limit:100,items:[{role_id:1,name:'sales',label:'销售',daily_limit:25},{role_id:2,name:'admin',label:'管理员',daily_limit:null}]}
const persist = () => sessionStorage.setItem('ai-chat-v2-fixture', JSON.stringify({sessions, nextId, nextMessage, store:[...store], limits}))
const body = config => typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {}
const total = {requests:12,completed:9,failed:2,stopped:1,input_tokens:18000,output_tokens:7000,token_requests:10,unpriced_requests:2,avg_first_token_ms:1200,avg_duration_ms:4300,failure_rate:2/11,estimated_costs:{USD:'0.123456'}}
for (const client of Object.values(clients)) if (client?.defaults) client.defaults.adapter = async config => {
  const url = config.url, method = config.method
  let data
  if (url === '/config') data = query.has('empty') ? {configured:false, models:[], message:'当前角色暂无可用模型，请联系管理员。'} : {configured:true, models, default_preset_id:1, usage:{remaining:99}}
  else if (url === '/modes') data = {items:[]}
  else if (url === '/admin/roles') data = {items:limits.items}
  else if (url === '/admin/role-limits' && method === 'get') data = limits
  else if (/^\/admin\/role-limits\/\d+$/.test(url) && method === 'put') { const role = limits.items.find(item => item.role_id === Number(url.split('/').at(-1))); role.daily_limit = body(config).daily_limit; data = limits; persist() }
  else if (url === '/admin/usage') data = {start:config.params?.start || '2026-11-10',end:config.params?.end || '2026-11-16',totals:total,models:[{...total,label:'模拟视觉模型',model:'fixture-model'}],users:[{...total,name:'模拟用户'}],days:[{...total,day:'2026-11-16'}]}
  else if (url === '/sessions' && method === 'get') { const start = Number(config.params?.cursor || 0); data = {items:sessions.slice(start,start+2), next_cursor:start+2 < sessions.length ? String(start+2) : null} }
  else if (url === '/sessions' && method === 'post') { data = {id:nextId++, title:`模拟对话 ${nextId-1}`, selected_preset_id:1}; sessions.unshift(data); store.set(data.id,[]); persist() }
  else if (/^\/sessions\/\d+$/.test(url)) { const id=Number(url.split('/')[2]); const index=sessions.findIndex(s=>s.id===id); if(method==='get') data={session:sessions[index],messages:store.get(id)||[],attachments:[]}; else if(method==='patch') { sessions[index]={...sessions[index],title:body(config).title}; data=sessions[index]; persist() } else if(method==='delete') { sessions.splice(index,1); store.delete(id); data={}; persist() } }
  else if (/^\/messages\/\d+\/selection$/.test(url) && method === 'patch') { const userId=Number(url.split('/')[2]); const list=[...store.values()].find(items=>items.some(item=>item.id===userId)); const user=list.find(item=>item.id===userId); user.selected_answer_id=body(config).answer_id; data=user; persist() }
  else throw new Error(`Fixture blocked unknown request: ${method} ${url}`)
  return {config,status:200,headers:{},data:{code:200,data:structuredClone(data)}}
}
window.fetch = async (url, options={}) => {
  const path = String(url)
  if (!/^\/api\/ai-chat\/(sessions\/\d+\/turns|messages\/\d+\/(retry|continue))\/stream$/.test(path)) throw new Error(`Fixture blocked fetch: ${path}`)
  const request=JSON.parse(options.body), continuing=path.includes('/continue/'), retry=path.includes('/retry/'), sourceId=(retry || continuing) ? Number(path.split('/')[4]) : null
  const id=sourceId ? [...store].find(([,messages])=>messages.some(m=>m.id===sourceId))?.[0] : Number(path.split('/')[4])
  const list=store.get(id), source=list.find(m=>m.id===sourceId), userId=source ? source.reply_to_message_id : nextMessage++, assistantId=nextMessage++, model=models.find(m=>m.preset_id===request.preset_id) || models[0]
  if (!source) list.push({id:userId,session_id:id,role:'user',content:request.content,status:'completed',selected_answer_id:null})
  const assistant={id:assistantId,session_id:id,role:'assistant',content:continuing ? source.content : '',reasoning_content:'',status:'streaming',model,reply_to_message_id:userId,request_id:request.request_id,retry_of_message_id:retry ? sourceId : null,continuation_of_message_id:continuing ? sourceId : null}; list.push(assistant); persist()
  const encoder=new TextEncoder(); const delay=Number(query.get('delay') || 1200)
  const stream=new ReadableStream({ start(controller) {
    const emit=(event,payload)=>controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`))
    emit('meta',{session_id:id,user_message_id:source ? null : userId,assistant_message_id:assistantId,reply_to_message_id:userId,model,status:'streaming'})
    if (continuing) emit('delta',{text:source.content})
    emit('reasoning',{text:'模拟推理：先核对输入。'}); assistant.reasoning_content='模拟推理：先核对输入。'
    const timer=setTimeout(()=>{ if (request.content?.includes('断流')) { assistant.status='failed'; assistant.error_message='模拟连接中断'; persist(); controller.close(); return } if (request.content?.includes('失败')) { assistant.status='failed';assistant.error_message='模拟生成失败';persist();emit('error',{message:assistant.error_message});controller.close();return } const text=continuing ? '\n\n模拟继续生成的补充内容。' : `${model.label} 的回答（版本 ${list.filter(m=>m.reply_to_message_id===userId).length}）：${request.content || '重新生成'}\n\n\`\`\`js\nconsole.log("hello")\n\`\`\``; assistant.content+=text; emit('delta',{text}); assistant.status='completed'; assistant.finish_reason=!source ? 'length' : 'stop'; list.find(m=>m.id===userId).selected_answer_id=assistantId; persist(); emit('done',{status:'completed',finish_reason:assistant.finish_reason});controller.close() },delay)
    options.signal?.addEventListener('abort',()=>{clearTimeout(timer);assistant.status='stopped';persist(); try { controller.error(new DOMException('Aborted','AbortError')) } catch {}},{once:true})
  } })
  return new Response(stream,{status:200,headers:{'content-type':'text/event-stream'}})
}
const pinia=createPinia(); const auth=useAuthStore(pinia); auth.user={id:7,roles:['super_admin'],permissions:[]}
const router=createRouter({history:createWebHashHistory(),routes:[{path:'/',name:'DesignAiChat',component:AiChat}]})
const app=createApp({setup(){const preset=ref('{"chat":{"enabled":true}}'); return () => query.has('operations') ? h('div',{style:'padding:24px'},[h('p','以下全部为模拟数据'),h(ChatOperations)]) : query.has('admin') ? h('div',{style:'padding:24px;max-width:650px'},[h('p','以下全部为模拟数据'),h(ElForm,{labelPosition:'top'},{default:()=>h(AiPresetChatFields,{modelValue:preset.value,'onUpdate:modelValue':v=>preset.value=v})}),h('pre',preset.value)]) : h('div',{style:'height:100dvh;box-sizing:border-box;padding:12px'},[h(AiChat)])}})
app.directive('permission', {})
app.component('DetailDrawer', DetailDrawer)
app.use(pinia).use(router).use(ElementPlus).mount('#app')
