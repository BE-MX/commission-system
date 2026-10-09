import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
import path from 'node:path'
const require=createRequire(import.meta.url)
const {chromium}=require(process.argv[2])
const base=process.argv[3]||'http://127.0.0.1:3212'
const output=process.argv[4]
await mkdir(output,{recursive:true})
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true})
const results=[]
try {
 for(const width of [1440,390,320]) {
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'})
  const page=await context.newPage();const errors=[],writes=[],unknown=[]
  let mode='normal',reviewed=false,reads=0,heldRead,releaseRead,heldPost,releasePost
  page.on('pageerror',error=>errors.push(error.message))
  function snapshot(id) {const editing=mode==='pending';return {invoice_id:id,invoice_no:'PI-SYNTHETIC-'+id,status:editing?'cancel_pending':'cancelled',version:'a'.repeat(64),
   cancellation:{status:editing?'pending':'retained',reason:'Synthetic reviewed cancellation',message:'本地处理已终止，记录保留'},outbound:null,
   recovery_summary:{review_required:editing?false:!reviewed,pending_attempt_count:editing||reviewed?0:1,last_observed_at:'2026-10-05T00:10:00+08:00',remote_observation:'absent'}}}
  await page.route(base+'/api/**',async route=>{
   const url=new URL(route.request().url());const match=/^\/api\/invoice\/invoices\/(\d+)\/lifecycle$/.exec(url.pathname)
   if(!match){unknown.push(url.pathname);await route.fulfill({status:503,json:{detail:'Unexpected isolated test endpoint'}});return}
   const id=Number(match[1]),request=route.request()
   if(request.method()==='GET') {
    ++reads;const captured=snapshot(id),readingMode=mode
    if(readingMode==='held-read') {heldRead=true;await new Promise(resolve=>releaseRead=resolve)}
    if(readingMode==='denied'||readingMode==='unavailable') {
     await route.fulfill({status:readingMode==='denied'?403:503,json:{detail:'Synthetic controlled rejection'}});return
    }
    await route.fulfill({json:{code:200,message:'ok',data:captured}})
   } else {
    const body=request.postDataJSON();writes.push({id,body});assert.equal(body.action,'refresh')
    if(mode==='held-post'){heldPost=true;await new Promise(resolve=>releasePost=resolve)}
    else reviewed=true
    await route.fulfill({json:{code:200,message:'ok',data:{status:'retained',recovery_summary:snapshot(id).recovery_summary}}})
   }
  })
  async function settledPanel(selector) {
   await page.waitForFunction(selector=>{
    const element=document.querySelector(selector)
    if(!element)return false
    const box=element.getBoundingClientRect()
    return box.width>0 && box.left>=-1 && box.right<=innerWidth+1 && getComputedStyle(element).transform==='none'
   },selector,{timeout:5000})
  }
  await page.goto(base+'/tests/invoiceLifecycleHarness.html')
  await page.getByRole('button',{name:'打开原任务',exact:true}).click()
  await page.getByRole('heading',{name:'PI-SYNTHETIC-1'}).waitFor()
  assert.equal(await page.getByRole('button',{name:'尝试删除小满订单',exact:true}).count(),0)
  await page.getByText('远端结果待核对；本地终止不代表远端单据仍存在',{exact:true}).waitFor()
  await settledPanel('.el-drawer');await page.screenshot({path:path.join(output,'retained-'+width+'.png'),fullPage:true})
  await page.getByRole('button',{name:'核对远端结果',exact:true}).click()
  await page.waitForFunction(()=>!document.body.innerText.includes('远端结果待核对；本地终止不代表远端单据仍存在'))
  assert.equal(writes.length,1)
  assert.equal(await page.getByRole('button',{name:'核对远端结果',exact:true}).count(),0)
  assert.equal(await page.getByText('本地处理状态：本地业务已终止，记录已保留',{exact:true}).count(),1)
  reviewed=false;mode='held-read'
  const oldRead=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/invoice/invoices/1/lifecycle' && response.request().method()==='GET')
  await page.getByRole('button',{name:'读取原任务结果',exact:true}).click()
  while(!heldRead)await page.waitForTimeout(10)
  await page.evaluate(()=>window.setInvoice(2));mode='normal'
  await page.getByRole('button',{name:'打开原任务',exact:true}).click()
  await page.getByRole('heading',{name:'PI-SYNTHETIC-2'}).waitFor()
  releaseRead();await (await oldRead).finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  assert.equal(await page.getByRole('heading',{name:'PI-SYNTHETIC-1'}).count(),0)
  mode='held-post';const oldPost=page.waitForResponse(response=>new URL(response.url()).pathname==='/api/invoice/invoices/2/lifecycle' && response.request().method()==='POST');await page.getByRole('button',{name:'核对远端结果',exact:true}).click()
  while(!heldPost)await page.waitForTimeout(10)
  await page.evaluate(()=>window.changeActor());mode='normal'
  await page.getByRole('button',{name:'打开原任务',exact:true}).click()
  await page.getByRole('heading',{name:'PI-SYNTHETIC-2'}).waitFor()
  const before=reads;releasePost();await (await oldPost).finished();await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))
  assert.equal(reads,before)
  assert.equal(writes.length,2)
  await page.getByText('远端结果待核对；本地终止不代表远端单据仍存在',{exact:true}).waitFor()
  mode='denied';await page.getByRole('button',{name:'读取原任务结果',exact:true}).click()
  const feedback=page.locator('[role="alert"][tabindex="-1"]')
  await feedback.waitFor();await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert')
  assert.equal(await page.getByRole('heading',{name:'PI-SYNTHETIC-2'}).count(),0)
  mode='unavailable';await page.getByRole('button',{name:'读取原任务结果',exact:true}).click()
  await page.getByText('原任务结果暂不可用，请稍后读取；不要重复发送。',{exact:true}).waitFor()
  const beforeRepeat=reads
  await page.getByRole('button',{name:'读取原任务结果',exact:true}).focus()
  await page.keyboard.press('Enter')
  while(reads===beforeRepeat)await page.waitForTimeout(10)
  assert.equal(reads,beforeRepeat+1)
  await page.waitForFunction(()=>document.activeElement?.getAttribute('role')==='alert')
  mode='pending';await page.getByRole('button',{name:'读取原任务结果',exact:true}).click()
  await page.getByRole('button',{name:'终止本地业务并保留记录',exact:true}).click()
  await settledPanel('.el-dialog');await page.getByRole('textbox',{name:'处理依据（10–500字）'}).fill('Private previous actor cancellation reason')
  await page.evaluate(()=>window.changeActor())
  await page.waitForFunction(()=>!document.body.innerText.includes('确认处理'))
  assert.equal(await page.getByRole('textbox',{name:'处理依据（10–500字）'}).count(),0)
  await page.getByRole('button',{name:'打开原任务',exact:true}).click()
  await page.getByRole('button',{name:'终止本地业务并保留记录',exact:true}).click()
  await page.getByRole('textbox',{name:'处理依据（10–500字）'}).fill('Private previous invoice cancellation reason')
  await page.evaluate(()=>window.setInvoice(3))
  await page.waitForFunction(()=>!document.body.innerText.includes('确认处理'))
  assert.equal(await page.getByRole('textbox',{name:'处理依据（10–500字）'}).count(),0)
  assert.equal(writes.length,2)
  await page.getByRole('button',{name:'打开原任务',exact:true}).click()
  await page.getByRole('heading',{name:'PI-SYNTHETIC-3'}).waitFor()
  await settledPanel('.el-drawer')
  const geometry=await page.evaluate(()=>({pageWidth:document.documentElement.scrollWidth,viewport:innerWidth,drawer:document.querySelector('.el-drawer').getBoundingClientRect().toJSON()}))
  assert.ok(geometry.pageWidth<=width+1,JSON.stringify(geometry))
  assert.deepEqual(errors,[]);assert.deepEqual(unknown,[])
  results.push({width,reads,writes:writes.length,lateReadIgnored:true,lateActorPostIgnored:true,deniedPrivateCleared:true,repeatedErrorFocused:true,privatePromptClearedOnActorAndInvoice:true,geometry,pageerrors:errors})
  await page.screenshot({path:path.join(output,'current-'+width+'.png'),fullPage:true})
  await context.close()
 }
 await writeFile(path.join(output,'result.json'),JSON.stringify({scope:'Isolated Vue component; all API responses synthetic, no real RBAC or persistence',results},null,2))
 console.log(JSON.stringify({status:'passed',results}))
} finally {await browser.close()}
