import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdir,writeFile} from 'node:fs/promises'
const {chromium}=createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE||'playwright')
const origin=process.env.PORTAL_PREVIEW_ORIGIN||'http://127.0.0.1:3211',output=process.env.PORTAL_QA_OUTPUT,motion=process.env.PORTAL_UI_MOTION||'reduce',target=process.env.PORTAL_NOTIFICATION_TARGET||'order'
assert.match(origin,/^http:\/\/127\.0\.0\.1:\d+$/);assert.ok(output);assert.ok(['order','mapping'].includes(target));assert.ok(['reduce','no-preference'].includes(motion));await mkdir(output,{recursive:true})
const widths=process.env.PORTAL_UI_WIDTHS?process.env.PORTAL_UI_WIDTHS.split(',').map(Number):[1440,390,320]
assert.ok(widths.length&&widths.every(x=>[1440,390,320].includes(x)))
function gate(){let release,complete;const waiting=new Promise(resolve=>release=resolve),completed=new Promise(resolve=>complete=resolve);return{waiting,release,completed,complete}}
async function reach(page,locator){await locator.waitFor({state:'attached'});for(let i=0;i<190;i++){if(await locator.evaluate(el=>el===document.activeElement))return;await page.keyboard.press('Tab')}throw new Error('Unreachable '+await locator.evaluate(el=>el.outerHTML))}
async function activate(page,locator,key='Enter'){await reach(page,locator);await page.keyboard.press(key)}
async function type(page,locator,value){await reach(page,locator);await page.keyboard.press('Control+A');await page.keyboard.press('Backspace');await page.keyboard.type(value);await page.keyboard.press('Tab')}
async function focused(page,locator){await locator.waitFor({state:'visible'});await page.waitForFunction(el=>el===document.activeElement,await locator.elementHandle());assert.equal(await locator.evaluate(el=>el===document.activeElement),true)}
async function geometry(page,dialog){assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);assert.deepEqual(await dialog.evaluate(el=>{const r=el.getBoundingClientRect(),bad=[];if(r.left< -1||r.right>innerWidth+1||r.top< -1||r.bottom>innerHeight+1||el.scrollWidth>el.clientWidth+1)bad.push('dialog');for(const b of el.querySelectorAll('.el-dialog__footer button,textarea')){const q=b.getBoundingClientRect();if(q.width&&(q.left<r.left-1||q.right>r.right+1||(b.closest('.el-dialog__footer')&&(q.top<r.top||q.bottom>r.bottom))))bad.push(b.textContent||b.getAttribute('aria-label'))}return bad}),[])}
const browser=await chromium.launch({executablePath:process.env.PORTAL_CHROMIUM,headless:true}),results=[]
try{for(const width of widths){
 const context=await browser.newContext({viewport:{width,height:950},reducedMotion:motion}),page=await context.newPage(),errors=[],writes=[]
 const id='11111111-1111-4111-8111-111111111111',eventId='22222222-2222-4222-8222-222222222222',itemId='33333333-3333-4333-8333-333333333333',reason='TransportRecoveryConfirmed'.repeat(23).slice(0,500)
 let readMode='fail',writeMode='ready',readGate,writeGate,eventStatus='dead',reads=0
 const base='/api/portal/admin/v1/'+(target==='order'?'orders/'+id:'customers/'+id+'/mapping')+'/notifications'
 const row=()=>({id:eventId,event_type:target==='order'?'business_mail':'mapping_mail',recipient_kind:'customer',status:eventStatus,attempt_count:8,created_at:'2026-10-04T10:00:00+08:00',next_attempt_at:null,error_code:eventStatus==='dead'?'MAIL_TRANSPORT_FAILED':null,retry_eligible:eventStatus==='dead',fingerprint:'a'.repeat(64)})
 const access={id,company_display_name:'Private notification buyer',status:'enabled',row_version:2,canonical_customer_id:'1',sales_user_id:'1',capabilities:{can_view_price:true,can_order:true},catalog_item_ids:[itemId],accounts:{items:[],total:0}}
 const order={request_id:id,request_no:'REQ-NOTIFICATION-KEYBOARD-001',status:'submitted',submitted_at:'2026-10-04T10:00:00+08:00',currency:'USD',product_amount:'100.00',items:[],delivery:{},customer_safe_timeline:[]}
 await context.addInitScript(()=>{localStorage.setItem('ark_access_token','synthetic-notification-keyboard');sessionStorage.setItem('leshine_welcome_shown_session','1')})
 page.on('pageerror',e=>errors.push(e.message))
 await context.route('**/*',route=>new URL(route.request().url()).origin===origin?route.continue():route.abort())
 await context.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname
  if(path==='/api/auth/me')return route.fulfill({json:{id:1,name:'QA',roles:[],permissions:['portal_order:read','portal_order:write','portal_access:read','portal_mapping:read','portal_mapping:write']}})
  if(path==='/api/auth/refresh')return route.fulfill({json:{access_token:'synthetic-notification-keyboard'}})
  let data={},readCompletion
  if(path===base){
   reads++;const mode=readMode;if(readGate){const current=readGate;readCompletion=current;readGate=null;await current.waiting}
   if(mode==='fail')return route.fulfill({status:503,json:{code:503,message:'通知记录暂不可用，请重试。',data:{error_code:'SERVICE_UNAVAILABLE'}}})
   const rows=Array.from({length:20},(_,i)=>({...row(),id:i?'event-'+i:eventId}));data={[target==='order'?'request_id':'access_id']:id,total:40,items:rows}
  }else if(path===base+'/'+eventId+'/retry'){
   const mode=writeMode;writes.push({key:req.headers()['idempotency-key'],body:req.postDataJSON(),path});if(writeGate){const current=writeGate;writeGate=null;await current.waiting}
   if(mode==='lost')return route.abort('failed')
   if(mode==='stale')return route.fulfill({status:409,json:{code:409,message:'通知记录已变化，请重新读取。',data:{error_code:'VERSION_CONFLICT'}}})
   if(mode==='denied')return route.fulfill({status:403,json:{code:403,message:'当前通知权限已撤销。',data:{error_code:'ACTION_FORBIDDEN'}}})
   if(mode==='fail')return route.fulfill({status:503,json:{code:503,message:'通知服务暂不可用，请保留原命令。',data:{error_code:'SERVICE_UNAVAILABLE'}}})
   eventStatus='pending';data={replayed:true,original_receipt:{[target==='order'?'request_id':'access_id']:mode==='wrong'?'wrong-scope':id,event_id:eventId,command_key:writes.at(-1).key,status:'pending'},current:{id:eventId,status:'pending'}}
  }else if(path.endsWith('/orders'))data={items:[order],total:1}
  else if(path.endsWith('/orders/'+id))data=order
  else if(path.endsWith('/customers'))data={items:[access],total:1}
  else if(path.endsWith('/customers/'+id))data=access
  else if(path.endsWith('/mapping'))data={access_id:id,row_version:2,mapping_version:1,entries:[{kind:'model',source_key:'MODEL',display_value:'Draft to preserve'}],sources:[{item_id:itemId,model_key:'MODEL',color_key:'BLACK',model_name:'Standard Weft',color_name:'Black',length:'20in',weight:'20g',unit:'pack',product_kind:'hair'}],draft:null}
  await route.fulfill({json:{code:200,message:'ok',data}});readCompletion?.complete()
 })
 const dialog=page.locator('.portal-notification-dialog:visible'),parent=page.locator('.portal-mapping-dialog:visible'),trigger=()=>target==='order'?page.getByRole('button',{name:'查看通知投递',exact:true}):parent.getByRole('button',{name:'查看映射通知',exact:true})
 const refresh=()=>dialog.getByRole('button',{name:'刷新投递记录',exact:true}),input=()=>dialog.getByRole('textbox',{name:'通知重试原因',exact:true}),confirm=()=>dialog.getByRole('checkbox'),submit=()=>dialog.getByRole('button',{name:'确认重新排队',exact:true}),replay=()=>dialog.getByRole('button',{name:'重放原重试命令',exact:true})
 async function read(){const current=gate();readGate=current;await activate(page,refresh());await dialog.getByRole('status').filter({hasText:'正在读取通知投递记录…'}).waitFor();assert.equal(await dialog.locator('.notification-content').getAttribute('aria-busy'),'true');current.release()}
 async function send(mode,again=false){writeMode=mode;const current=gate();writeGate=current;await activate(page,again?replay():submit());await dialog.getByRole('status').filter({hasText:'正在重新排队通知，请等待回执…'}).waitFor();assert.equal(await dialog.locator('.notification-content').getAttribute('aria-busy'),'true');current.release()}
 try{
  await page.goto(origin+(target==='order'?'/portal/orders?request='+id:'/portal/customers'))
  if(target==='mapping'){await activate(page,page.getByRole('button',{name:'管理',exact:true}));await activate(page,page.getByRole('button',{name:'型号颜色映射',exact:true}));await parent.getByRole('textbox',{name:'客户展示名 1',exact:true}).waitFor();await type(page,parent.getByRole('textbox',{name:'客户展示名 1',exact:true}),'Draft to preserve')}
  await activate(page,trigger());const failed=dialog.getByRole('alert').filter({hasText:'通知记录暂不可用，请重试。'});await focused(page,failed);await activate(page,refresh());await focused(page,failed);assert.equal(writes.length,0)
  readMode='ready';await read();await focused(page,dialog.getByRole('alert').filter({hasText:'已读取当前通知投递记录。'}));assert.equal(await dialog.locator('.el-table__body tr').count(),20)
  const scroll=dialog.locator('.el-table .el-scrollbar__wrap');if(width<600){await reach(page,scroll);await page.keyboard.press('ArrowRight');await page.waitForFunction(el=>el.scrollLeft>0,await scroll.elementHandle())}
  await activate(page,dialog.getByRole('button',{name:'申请重试',exact:true}).first());await focused(page,input());await type(page,input(),reason);await activate(page,confirm(),'Space');await reach(page,input());await page.keyboard.press('ArrowLeft');await page.keyboard.press('ArrowRight');await page.keyboard.press('Tab');assert.equal(await confirm().isChecked(),true)
  await type(page,input(),reason.slice(0,-1));assert.equal(await confirm().isChecked(),false);assert.equal(await submit().isDisabled(),true);await type(page,input(),reason);await activate(page,confirm(),'Space');await geometry(page,dialog);await page.screenshot({path:output+'/prepared-'+target+'-'+width+'.png',fullPage:true})
  await send('stale');const stale=dialog.getByRole('alert').filter({hasText:'通知记录已变化，请重新读取。'});await focused(page,stale);await send('stale');await focused(page,stale);assert.equal(await input().inputValue(),reason)
  await send('lost');await focused(page,dialog.getByRole('alert').filter({hasText:'网络连接中断，请按页面提示核对。'}));assert.equal(await input().isDisabled(),true);assert.equal(await confirm().isDisabled(),true);assert.equal(await refresh().isDisabled(),true);await page.keyboard.press('Escape');assert.equal(await dialog.count(),1)
  const before=writes.length,unloadEvent=page.waitForEvent('dialog'),reload=page.reload({timeout:5000}).then(()=>false,()=>true),unload=await unloadEvent;assert.equal(unload.type(),'beforeunload');await unload.dismiss();assert.equal(await reload,true);assert.equal(writes.length,before)
  await send('denied',true);await focused(page,dialog.getByRole('alert').filter({hasText:'当前通知权限已撤销。'}));assert.equal(await input().count(),0);assert.equal(await dialog.getByText('邮件服务暂时失败',{exact:true}).count(),0)
  await send('fail',true);await focused(page,dialog.getByRole('alert').filter({hasText:'通知服务暂不可用，请保留原命令。'}));await send('wrong',true);await focused(page,dialog.getByRole('alert').filter({hasText:'未收到匹配的重试回执，请核对原命令。'}));await send('ready',true)
  await focused(page,dialog.getByRole('alert').filter({hasText:'通知已重新排队，请核对当前投递记录。'}));assert.equal(writes.length,7);for(const call of writes.slice(2))assert.deepEqual(call,writes[2]);assert.equal(await replay().count(),0);assert.equal(reads,4);await geometry(page,dialog)
  await activate(page,dialog.getByRole('button',{name:'关闭',exact:true}));await dialog.waitFor({state:'hidden'});await focused(page,trigger());if(target==='mapping')assert.equal(await parent.getByRole('textbox',{name:'客户展示名 1',exact:true}).inputValue(),'Draft to preserve')
  await activate(page,trigger());await focused(page,dialog.getByRole('alert').filter({hasText:'已读取当前通知投递记录。'}))
  const late=gate();readGate=late;await activate(page,refresh());await dialog.getByRole('status').filter({hasText:'正在读取通知投递记录…'}).waitFor();await activate(page,dialog.getByRole('button',{name:'关闭',exact:true}));await dialog.waitFor({state:'hidden'});await focused(page,trigger())
  const newFocus=target==='order'?page.getByRole('button',{name:'查看操作审计',exact:true}):parent.getByRole('textbox',{name:'客户展示名 1',exact:true});await reach(page,newFocus);late.release();await late.completed;await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));await focused(page,newFocus);assert.equal(reads,6);assert.equal(writes.length,7)
  assert.deepEqual(errors,[]);results.push({width,motion,target,writes:writes.length,reads,pureKeyboard:true,lateReadDoesNotStealFocus:true,scope:'Synthetic API/UI only; no SMTP or DB commit-loss proof'})
 }catch(e){await writeFile(output+'/failure-'+target+'-'+width+'.json',JSON.stringify({errors,writes,reads,url:page.url(),body:(await page.locator('body').innerText()).slice(0,4500)},null,2));throw e}finally{readGate?.release();writeGate?.release();await context.close()}
}}finally{await browser.close()}
await writeFile(output+'/result.json',JSON.stringify(results,null,2));console.log(JSON.stringify({status:'pass',results}))
