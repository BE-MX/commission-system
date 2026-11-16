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
import { useAuthStore } from '../../../src/stores/auth'
import * as clients from '../../../src/api/clients'

const query = new URLSearchParams(location.search)
const models = [{preset_id: 1, label: '视觉模型', vision: true}, {preset_id: 2, label: '文字模型', vision: false}]
const sessions = []
let nextId = 1, nextMessage = 100
const store = new Map()
const body = config => typeof config.data === 'string' ? JSON.parse(config.data) : config.data || {}
for (const client of Object.values(clients)) if (client?.defaults) client.defaults.adapter = async config => {
  const url = config.url, method = config.method
  let data
  if (url === '/config') data = query.has('empty') ? {configured:false, models:[], message:'当前角色暂无可用模型，请联系管理员。'} : {configured:true, models, default_preset_id:1, usage:{remaining:99}}
  else if (url === '/modes') data = {items:[]}
  else if (url === '/admin/roles') data = {items:[{name:'sales',label:'销售'},{name:'admin',label:'管理员'}]}
  else if (url === '/sessions' && method === 'get') { const start = Number(config.params?.cursor || 0); data = {items:sessions.slice(start,start+2), next_cursor:start+2 < sessions.length ? String(start+2) : null} }
  else if (url === '/sessions' && method === 'post') { data = {id:nextId++, title:`新对话 ${nextId-1}`, selected_preset_id:1}; sessions.unshift(data); store.set(data.id,[]) }
  else if (/^\/sessions\/\d+$/.test(url)) { const id=Number(url.split('/')[2]); const index=sessions.findIndex(s=>s.id===id); if(method==='get') data={session:sessions[index],messages:store.get(id)||[],attachments:[]}; else if(method==='patch') { sessions[index]={...sessions[index],title:body(config).title}; data=sessions[index] } else if(method==='delete') { sessions.splice(index,1); store.delete(id); data={} } }
  else throw new Error(`Fixture blocked unknown request: ${method} ${url}`)
  return {config,status:200,headers:{},data:{code:200,data}}
}
window.fetch = async (url, options={}) => {
  const path = String(url)
  if (!/^\/api\/ai-chat\/(sessions\/\d+\/turns|messages\/\d+\/retry)\/stream$/.test(path)) throw new Error(`Fixture blocked fetch: ${path}`)
  const data=JSON.parse(options.body), retry=path.includes('/retry/'), id=retry ? [...store].find(([,messages])=>messages.some(m=>m.id===Number(path.split('/')[4])))?.[0] : Number(path.split('/')[4]);
  const list=store.get(id); const userId=retry ? null : nextMessage++, assistantId=nextMessage++, model=models.find(m=>m.preset_id===data.preset_id)
  if (!retry) list.push({id:userId,role:'user',content:data.content,status:'completed'})
  const assistant={id:assistantId,role:'assistant',content:'',reasoning_content:'',status:'streaming',model}; list.push(assistant)
  const encoder=new TextEncoder(); const delay=Number(query.get('delay') || 1200)
  const stream=new ReadableStream({ start(controller) {
    const emit=(event,payload)=>controller.enqueue(encoder.encode(`event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`))
    emit('meta',{session_id:id,user_message_id:userId,assistant_message_id:assistantId,model,status:'streaming'})
    emit('reasoning',{text:'模拟推理：先核对输入。'}); assistant.reasoning_content='模拟推理：先核对输入。'
    let timer=setTimeout(()=>{ if (data.content?.includes('失败')) { assistant.status='failed';assistant.error_message='模拟生成失败';emit('error',{message:assistant.error_message});controller.close();return } assistant.content=`${model.label} 的回答：${data.content || '重新生成'}\n\n\`\`\`js\nconsole.log("hello")\n\`\`\``; emit('delta',{text:assistant.content}); assistant.status='completed';emit('done',{status:'completed'});controller.close() },delay)
    options.signal?.addEventListener('abort',()=>{clearTimeout(timer);assistant.status='stopped'; try { controller.error(new DOMException('Aborted','AbortError')) } catch {}},{once:true})
  } })
  return new Response(stream,{status:200,headers:{'content-type':'text/event-stream'}})
}
const pinia=createPinia(); const auth=useAuthStore(pinia); auth.user={id:7,roles:['super_admin'],permissions:[]}
const router=createRouter({history:createWebHashHistory(),routes:[{path:'/',name:'DesignAiChat',component:AiChat}]})
const app=createApp({setup(){const preset=ref('{"chat":{"enabled":true}}'); return () => query.has('admin') ? h('div',{style:'padding:24px;max-width:650px'},[h(ElForm,{labelPosition:'top'},{default:()=>h(AiPresetChatFields,{modelValue:preset.value,'onUpdate:modelValue':v=>preset.value=v})}),h('pre',preset.value)]) : h('div',{style:'height:100dvh;box-sizing:border-box;padding:12px'},[h(AiChat)])}})
app.component('DetailDrawer', DetailDrawer)
app.use(pinia).use(router).use(ElementPlus).mount('#app')
