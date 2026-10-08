import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require=createRequire(import.meta.url)
const {chromium}=require(process.env.PORTAL_PLAYWRIGHT_MODULE||'playwright')
const browser=await chromium.launch({executablePath:process.env.PORTAL_CHROMIUM,headless:true})
const context=await browser.newContext({viewport:{width:1440,height:1000}})
const page=await context.newPage()
const accessId='11111111-1111-4111-8111-111111111111',eventId='22222222-2222-4222-8222-222222222222',itemId='33333333-3333-4333-8333-333333333333'
const errors=[],posts=[]
let canWrite=true,deny=false,wrongReceipt=false,eventStatus='dead'
page.on('pageerror',e=>errors.push(e.message))
await context.addInitScript(()=>{localStorage.setItem('ark_access_token','synthetic-mapping-notification');sessionStorage.setItem('leshine_welcome_shown_session','1')})
await context.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname
  if(path==='/api/auth/me') return route.fulfill({json:{id:1,name:'QA',roles:[],permissions:['portal_access:read','portal_mapping:read','portal_order:read',...(canWrite?['portal_mapping:write']:[])]}})
  if(path==='/api/auth/refresh') return route.fulfill({json:{access_token:'synthetic-mapping-notification'}})
  const access={id:accessId,company_display_name:'Mapping delivery QA',status:'enabled',row_version:2,canonical_customer_id:'1',sales_user_id:'1',capabilities:{can_view_price:true,can_order:true},catalog_item_ids:[itemId],accounts:{items:[],total:0}}
  const base='/api/portal/admin/v1/customers/'+accessId+'/mapping/notifications'
  let data={}
  if(path===base+'/'+eventId+'/retry'){
    posts.push({path,key:req.headers()['idempotency-key'],body:req.postDataJSON()})
    if(posts.length===1) return route.abort('failed')
    if(deny) return route.fulfill({status:403,json:{code:403,message:'映射操作权限已撤销。',data:{error_code:'ACTION_FORBIDDEN'}}})
    const scope=wrongReceipt?{request_id:accessId}:{access_id:accessId}
    eventStatus='pending'
    data={replayed:true,original_receipt:{...scope,event_id:eventId,command_key:posts.at(-1).key,status:'pending'},current:{id:eventId,status:'pending'}}
  }else if(path===base){
    data={access_id:accessId,total:1,items:[{id:eventId,event_type:'mapping_mail',recipient_kind:'customer',status:eventStatus,attempt_count:8,created_at:'2026-10-04T10:00:00+08:00',next_attempt_at:null,error_code:eventStatus==='dead'?'MAIL_TRANSPORT_FAILED':null,retry_eligible:eventStatus==='dead',fingerprint:'a'.repeat(64)}]}
  }else if(path.endsWith('/customers')) data={items:[access],total:1}
  else if(path.endsWith('/customers/'+accessId)) data=access
  else if(path.endsWith('/mapping')) data={access_id:accessId,row_version:2,mapping_version:1,entries:[{kind:'model',source_key:'MODEL',display_value:'Silk Collection'}],sources:[{item_id:itemId,model_key:'MODEL',color_key:'BLACK',model_name:'Standard Weft',color_name:'Black',length:'20in',weight:'20g',unit:'pack',product_kind:'hair'}],draft:null}
  else if(path.endsWith('/orders')) data={items:[],total:0}
  return route.fulfill({json:{code:200,message:'ok',data}})
})
const parent=()=>page.locator('.portal-mapping-dialog:visible')
const dialog=()=>page.locator('.portal-notification-dialog:visible')
async function open(){
  await page.goto('http://127.0.0.1:3211/portal/customers')
  await page.getByRole('cell',{name:'Mapping delivery QA',exact:true}).waitFor()
  await page.getByRole('button',{name:'管理',exact:true}).click()
  await page.getByRole('button',{name:'型号颜色映射',exact:true}).click()
  await parent().getByRole('textbox',{name:'客户展示名 1',exact:true}).waitFor()
  if(canWrite) await parent().getByRole('textbox',{name:'客户展示名 1',exact:true}).fill('Unpublished draft kept')
  await parent().getByRole('button',{name:'查看映射通知',exact:true}).click()
  await dialog().getByText('映射更新邮件',{exact:true}).waitFor()
}
try{
  await open()
  await dialog().getByText('映射已发布，通知投递失败不影响显示名称。',{exact:false}).waitFor()
  await dialog().getByRole('button',{name:'申请重试',exact:true}).click()
  await dialog().getByRole('textbox').fill('Mail transport recovered')
  await dialog().locator('.el-checkbox').click()
  await page.screenshot({path:process.env.PORTAL_QA_OUTPUT+'/mapping-notifications-1440.png',animations:'disabled',fullPage:true})
  for(const width of [390,320]){
    await page.setViewportSize({width,height:844})
    assert.ok(await dialog().evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    assert.ok(await dialog().getByRole('button',{name:'确认重新排队',exact:true}).isEnabled())
    await page.screenshot({path:process.env.PORTAL_QA_OUTPUT+`/mapping-notifications-${width}.png`,animations:'disabled',fullPage:true})
  }
  await dialog().getByRole('button',{name:'确认重新排队',exact:true}).click()
  await dialog().getByText('重试结果待核对。请勿关闭或刷新浏览器，只重放原命令获取回执。',{exact:true}).waitFor()
  assert.ok(await dialog().getByRole('textbox').isDisabled())
  assert.ok(await dialog().getByRole('checkbox').isDisabled())
  assert.ok(await dialog().getByRole('button',{name:'刷新投递记录',exact:true}).isDisabled())
  assert.ok(await parent().getByRole('textbox',{name:'客户展示名 1',exact:true}).isDisabled())
  assert.ok(await parent().getByRole('button',{name:'重新读取当前版本（舍弃草稿）',exact:true}).isDisabled())
  await page.keyboard.press('Escape')
  assert.equal(await dialog().count(),1);assert.equal(await parent().count(),1)
  const unload=page.waitForEvent('dialog')
  const reload=page.reload().catch(()=>null)
  const prompt=await unload;assert.equal(prompt.type(),'beforeunload');await prompt.dismiss();await reload
  deny=true
  await dialog().getByRole('button',{name:'重放原重试命令',exact:true}).click()
  await dialog().getByText('映射操作权限已撤销。',{exact:true}).waitFor()
  assert.equal(await dialog().getByRole('textbox').count(),0)
  deny=false;wrongReceipt=true
  await dialog().getByRole('button',{name:'重放原重试命令',exact:true}).click()
  await dialog().getByText('未收到匹配的重试回执，请核对原命令。',{exact:true}).waitFor()
  assert.equal(await dialog().getByRole('button',{name:'重放原重试命令',exact:true}).count(),1)
  wrongReceipt=false
  await dialog().getByRole('button',{name:'重放原重试命令',exact:true}).click()
  await dialog().getByText('等待投递',{exact:true}).waitFor()
  assert.equal(posts.length,4)
  for(const call of posts) assert.deepEqual(call,posts[0])
  await dialog().getByRole('button',{name:'关闭',exact:true}).click()
  assert.equal(await dialog().count(),0)
  assert.equal(await parent().getByRole('textbox',{name:'客户展示名 1',exact:true}).inputValue(),'Unpublished draft kept')
  canWrite=false;eventStatus='dead'
  await open()
  assert.equal(await dialog().getByRole('button',{name:'申请重试',exact:true}).count(),0)
  assert.equal(await dialog().getByRole('button',{name:'确认重新排队',exact:true}).count(),0)
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({status:'pass',scenarios:12,simulatedWrites:posts.length,scope:'Synthetic API browser UI only'}))
}catch(e){console.error(JSON.stringify({errors,body:(await page.locator('body').innerText()).slice(0,3000)}));throw e}
finally{await browser.close()}