import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
const require=createRequire(import.meta.url),{chromium}=require(process.argv[2])
const base=process.argv[3],output=process.argv[4],motion=process.argv[5]||'reduce'
await mkdir(output,{recursive:true})
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true})
const results=[]
try {
 for(const width of [1440,390,320]) {
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:motion})
  const page=await context.newPage();const errors=[],writes=[],unknown=[]
  let mode='unbound',reviewed=false,reads=0,held=false,release,heldRead=false,releaseRead,denialStatus=403
  const reference='7'.repeat(64)
  page.on('pageerror',error=>errors.push(error.message))
  function snapshot(id){return {invoice_id:id,invoice_no:'PI-SYNTHETIC-'+id,status:'ready',version:'a'.repeat(64),cancellation:null,outbound:null,
   recovery_summary:{review_required:false,pending_attempt_count:0,last_observed_at:null,remote_observation:'not_checked'},
   order_push_summary:{review_required:!reviewed,pending_attempt_count:reviewed?0:1,last_observed_at:'2026-10-05T00:10:00+08:00',
    result_class:mode==='unknown'?'unknown':'accepted',original_order_id:reviewed||mode==='unknown'?null:reference,
    resolution:reviewed||mode==='unknown'?null:mode==='bound'?'confirm_existing':'bind_order'}}}
  await page.route(base+'/api/**',async route=>{
   const pathname=new URL(route.request().url()).pathname,request=route.request()
   const get=/^\/api\/invoice\/invoices\/(\d+)\/lifecycle$/.exec(pathname)
   const post=/^\/api\/invoice\/invoices\/(\d+)\/sync-uncertain\/resolve$/.exec(pathname)
   if(get&&request.method()==='GET') {
    ++reads
    const captured=snapshot(Number(get[1]))
    if(mode==='held-read'){heldRead=true;await new Promise(resolve=>releaseRead=resolve)}
    if(mode==='expired'){await route.fulfill({status:401,json:{detail:'Session expired'}});return}
    if(mode==='denied'){await route.fulfill({status:denialStatus,json:{detail:'Synthetic current permission rejected'}});return}
    await route.fulfill({json:{code:200,message:'ok',data:captured}});return
   }
   if(post&&request.method()==='POST') {
    const body=request.postDataJSON();writes.push({id:Number(post[1]),body})
    assert.deepEqual(Object.keys(body).sort(),['reason','resolution','xiaoman_order_id'])
    assert.equal(body.resolution,mode==='bound'?'confirm_existing':'bind_order')
    assert.equal(body.xiaoman_order_id,mode==='bound'?null:reference)
    assert.ok(body.reason.length>=10&&body.reason.length<=500)
    const captured=mode
    if(captured==='held'){held=true;await new Promise(resolve=>release=resolve)}
    if(captured==='post-denied'){await route.fulfill({status:403,json:{detail:'Synthetic current action rejected'}});return}
    if(captured==='unavailable'){await route.fulfill({status:503,json:{detail:'Synthetic evidence unavailable'}});return}
    if(captured!=='held')reviewed=true
    await route.fulfill({json:{code:200,message:'ok',data:{id:Number(post[1])}}});return
   }
   unknown.push(pathname);await route.fulfill({status:503,json:{detail:'Unexpected isolated endpoint'}})
  })
  await page.route(base+'/login',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><p>Session expired</p>'}))
  async function tick(){await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))}
  async function open(){await page.getByRole('button',{name:'打开原任务',exact:true}).click();await page.getByRole('heading',{name:/PI-SYNTHETIC/}).waitFor()}
  const button=()=>page.getByRole('button',{name:'核对原推送订单',exact:true})
  const reason=()=>page.getByRole('textbox',{name:'处理依据（10–500字）'})
  const confirm=()=>page.getByRole('button',{name:'确认执行',exact:true})
  async function prompt(){await button().focus();await page.keyboard.press('Enter');await reason().waitFor();await page.waitForFunction(()=>document.activeElement?.id==='invoice-lifecycle-reason')}
  async function submit(value){await reason().fill(value);await confirm().focus();await page.keyboard.press('Enter')}
  await page.goto(base+'/tests/invoiceLifecycleHarness.html');await open()
  await page.getByText('原订单推送结果待核对，请勿再次创建订单',{exact:true}).waitFor()
  await prompt();assert.equal(await page.locator('.el-dialog input').count(),0)
  await submit('too short');await page.getByText('请填写10–500字的处理依据',{exact:true}).waitFor()
  await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');assert.equal(writes.length,0)
  await submit('核'.repeat(500));await page.waitForFunction(()=>window.changed===1)
  assert.equal(writes.length,1);assert.equal(writes[0].body.reason.length,500)
  assert.equal(await button().count(),0);await page.waitForFunction(()=>document.activeElement?.innerText==='读取原任务结果')
  mode='bound';reviewed=false;await page.getByRole('button',{name:'读取原任务结果',exact:true}).click();await prompt()
  await reason().fill('Private old prompt');await page.keyboard.press('Escape')
  await page.waitForFunction(()=>document.activeElement?.innerText==='核对原推送订单')
  await prompt();assert.equal(await reason().inputValue(),'');await submit('已人工核对当前绑定原订单全部商业依据')
  await page.waitForFunction(()=>window.changed===2);assert.equal(writes.length,2)
  mode='unknown';reviewed=false;await page.getByRole('button',{name:'读取原任务结果',exact:true}).click()
  await page.getByText('当前不能直接解除保护，请先核对原执行状态与处理依据。',{exact:true}).waitFor();assert.equal(await button().count(),0)
  mode='unavailable';await page.getByRole('button',{name:'读取原任务结果',exact:true}).click();await prompt();await submit('已核对原单但供应商当前证据暂不可用')
  await page.getByText('本次核对未确认，请查看原任务最新状态后再处理。',{exact:true}).waitFor()
  await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert');assert.equal(writes.length,3)
  await page.getByRole('button',{name:'读取原任务结果',exact:true}).click();assert.equal(writes.length,3)
  mode='held';await prompt();const oldPost=page.waitForResponse(r=>r.url().includes('/sync-uncertain/resolve'));await submit('原账号在途核对依据不会泄露给下个账号')
  while(!held)await page.waitForTimeout(10)
  await page.evaluate(()=>window.changeActor());mode='unbound';await open()
  const before=reads;release();await (await oldPost).finished();await tick()
  assert.equal(reads,before);assert.equal(await page.evaluate(()=>window.changed),2);assert.equal(writes.length,4)
  mode='held-read';const oldRead=page.waitForResponse(r=>r.url().includes('/invoices/1/lifecycle')&&r.request().method()==='GET')
  await page.getByRole('button',{name:'读取原任务结果',exact:true}).click()
  while(!heldRead)await page.waitForTimeout(10)
  await page.evaluate(()=>window.setInvoice(3));mode='unbound';await open()
  releaseRead();await (await oldRead).finished();await tick()
  assert.equal(await page.getByRole('heading',{name:'PI-SYNTHETIC-1'}).count(),0)
  assert.equal(await page.getByRole('heading',{name:'PI-SYNTHETIC-3'}).count(),1)
  await prompt();await reason().fill('Private old invoice reason');await page.evaluate(()=>window.setInvoice(2))
  await page.waitForFunction(()=>!document.body.innerText.includes('确认处理'));assert.equal(await reason().count(),0)
  await open();await page.getByRole('heading',{name:'PI-SYNTHETIC-2'}).waitFor()
  for(const status of [403,404]) {
   mode='denied';denialStatus=status;await page.getByRole('button',{name:'读取原任务结果',exact:true}).click()
   await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert')
   assert.equal(await page.getByRole('heading',{name:'PI-SYNTHETIC-2'}).count(),0)
   assert.equal(await page.getByText(reference,{exact:false}).count(),0)
   mode='unbound';await page.getByRole('button',{name:'读取原任务结果',exact:true}).click();await button().waitFor()
  }
  mode='post-denied';await prompt();const beforeDenied=reads;await submit('当前执行权限失效后不得返回此前客户数据')
  await page.getByText('当前权限已变化，无法确认原操作结果；请由有权人员核对。',{exact:true}).waitFor()
  assert.equal(reads,beforeDenied);assert.equal(writes.length,5)
  assert.equal(await page.getByRole('heading',{name:'PI-SYNTHETIC-2'}).count(),0)
  assert.equal(await page.getByText(reference,{exact:false}).count(),0)
  mode='unbound';await page.getByRole('button',{name:'读取原任务结果',exact:true}).click();await prompt();await reason().fill('Private same actor role revocation reason')
  await page.evaluate(()=>window.revokeSameActor());await page.waitForFunction(()=>!document.body.innerText.includes('确认处理'))
  assert.equal(await reason().count(),0);assert.equal(await page.getByRole('heading',{name:'PI-SYNTHETIC-2'}).count(),0)
  await page.evaluate(()=>window.changeActor());await open()
  await page.waitForFunction(()=>{const d=document.querySelector('.el-drawer');return d&&getComputedStyle(d).transform==='none'})
  const geometry=await page.evaluate(()=>({pageWidth:document.documentElement.scrollWidth,viewport:innerWidth,
   drawerWidth:document.querySelector('.el-drawer').scrollWidth,drawerClient:document.querySelector('.el-drawer').clientWidth}))
  assert.ok(geometry.pageWidth<=width+1&&geometry.drawerWidth<=geometry.drawerClient+1,JSON.stringify(geometry))
  assert.deepEqual(errors,[]);assert.deepEqual(unknown,[])
  await page.screenshot({path:path.join(output,'order-push-'+width+'.png'),fullPage:true})
  mode='expired';await page.getByRole('button',{name:'读取原任务结果',exact:true}).click();await page.waitForURL(base+'/login')
  assert.equal(await page.getByRole('heading',{name:'PI-SYNTHETIC-2'}).count(),0);assert.ok(!(await page.locator('body').innerText()).includes(reference))
  assert.deepEqual(errors,[]);assert.deepEqual(unknown,[])
  results.push({width,motion,reads,writes:writes.length,keyboardInvalidAndSuccess:true,canonicalReferenceCaptured:true,
   noBlindRetry:true,lateActorPostIgnored:true,lateInvoiceGetIgnored:true,deniedPrivateCleared:true,sessionExpiredRedirectCleared:true,promptInvoiceAndSameActorRoleCleared:true,geometry,pageerrors:errors})
  await context.close()
 }
 await writeFile(path.join(output,'result.json'),JSON.stringify({scope:'Actual Vue component, synthetic API; backend authorization and persistence verified separately',results},null,2))
 console.log(JSON.stringify({status:'passed',results}))
} finally {await browser.close()}
