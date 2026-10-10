import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const require=createRequire(import.meta.url), {chromium}=require(process.argv[2])
const base=process.argv[3],output=process.argv[4],red=process.argv[5]==='--red-close',geometryOnly=process.argv[5]==='--red-geometry'
await mkdir(output,{recursive:true})
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true})
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO6sAAAAASUVORK5CYII=','base64'),results=[]
try {
for(const width of red?[1440]:geometryOnly?[320]:[1440,390,320]) {
  const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'})
  const page=await context.newPage(),errors=[],writes=[],queries=[],unknown=[],cancelled=[]
  let mode='initial-denied',committed=null,hold=false,release,heldKind='',heldTerminal,settleHeld
  page.on('pageerror',error=>errors.push(error.message));page.on('dialog',dialog=>dialog.accept())
  const invoice={id:1,invoice_no:'PI-PRIVATE-ONE',customer_id:'customer-1',customer_name:'PRIVATE CUSTOMER',currency:'USD',sync_status:'synced'}
  const receipt=body=>({id:7,request_key:body.request_key,status:'active',items:[{invoice_id:1,amount:'10'}]})
  const ok=(route,data)=>route.fulfill({json:{code:200,message:'ok',data}})
  await page.route(base+'/api/**',async route=>{
    const request=route.request(),path=new URL(request.url()).pathname
    if(path==='/api/receipts/order-options')return mode==='initial-denied'?route.fulfill({status:403,json:{detail:'Current synthetic scope denied'}}):ok(route,{items:[invoice]})
    if(path==='/api/receipts/types')return ok(route,['T/T'])
    if(path==='/api/receipts/order-balance/1')return mode==='balance-denied'?route.fulfill({status:404,json:{detail:'Current synthetic invoice hidden'}}):ok(route,{remaining_amount:'100.00',version:'a'.repeat(64),currency:'USD',settlement_id:null})
    if(path==='/api/receipts/attachments'&&request.method()==='POST')return ok(route,{id:'synthetic-proof',name:'payment.png'})
    if(path==='/api/receipts/attachments/synthetic-proof')return route.fulfill({contentType:'image/png',body:png})
    if(path==='/api/receipts/batches') {
      const body=request.postDataJSON(),captured=mode;writes.push(body)
      if(captured==='held-post'){heldTerminal=new Promise(resolve=>settleHeld=resolve);hold=true;heldKind='post';await new Promise(resolve=>release=resolve)}
      if(captured==='post-denied')return route.fulfill({status:403,json:{detail:'Current synthetic write denied'}})
      if(captured==='unknown')return route.fulfill({status:503,json:{detail:'Synthetic original result unknown'}})
      if(captured==='malformed')return ok(route,{...receipt(body),id:false})
      committed=body
      try{return await ok(route,receipt(body))}catch(error){if(captured==='held-post')cancelled.push(error.message);else throw error}finally{if(captured==='held-post')settleHeld()}
    }
    if(path==='/api/receipts/batches/submission-status') {
      const body=request.postDataJSON(),captured=mode;queries.push(body)
      if(captured==='held-status'){heldTerminal=new Promise(resolve=>settleHeld=resolve);hold=true;heldKind='status';await new Promise(resolve=>release=resolve)}
      if(captured==='status-denied')return route.fulfill({status:403,json:{detail:'Current synthetic recovery denied'}})
      if(captured==='bad-status')return ok(route,{state:'found',request_key:body.request_key,batch:{...receipt(body),request_key:'wrong'}})
      const value=committed?.request_key===body.request_key?{state:'found',request_key:body.request_key,batch:receipt(body)}:{state:'not_found',request_key:body.request_key,invoices:[invoice]}
      try{return await ok(route,value)}catch(error){if(captured==='held-status')cancelled.push(error.message);else throw error}finally{if(captured==='held-status')settleHeld()}
    }
    unknown.push(path);return route.fulfill({status:503,json:{detail:'Unexpected isolated endpoint'}})
  })
  // Persistent error feedback can overlap the harness launcher; use its keyboard path.
  const open=async()=>{const button=page.getByRole('button',{name:'打开批次回款',exact:true});await button.focus();await button.press('Enter')}
  const cancel=()=>page.getByRole('button',{name:'取消',exact:true})
  const inspect=()=>page.getByRole('button',{name:'核对原提交（只查询）',exact:true}).click()
  async function waitText(text){await page.getByText(text,{exact:false}).first().waitFor()}
  async function tick(){await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))}
  async function fill() {
    await page.locator('.el-form .el-select').first().click();await page.getByRole('option',{name:/PI-PRIVATE-ONE/}).click()
    await page.getByText('100.00',{exact:true}).waitFor()
    await page.locator('.el-table').getByRole('spinbutton').fill('10');await page.keyboard.press('Tab')
    await page.locator('.fields-grid .el-form-item').filter({hasText:'本次回款金额'}).getByRole('spinbutton').fill('10');await page.keyboard.press('Tab')
    await page.locator('.fields-grid .el-select').click();await page.getByRole('option',{name:'T/T',exact:true}).click()
    await page.locator('input[type=file]').setInputFiles({name:'payment.png',mimeType:'image/png',buffer:png})
    await page.locator('textarea').fill('ORIGINAL PRIVATE NOTE')
    await page.getByRole('button',{name:'创建回款单',exact:true}).waitFor()
  }
  async function submitUnknown(){mode='unknown';await page.getByRole('button',{name:'创建回款单',exact:true}).click();await waitText('Synthetic original result unknown');assert.equal(await cancel().isDisabled(),true)}
  await page.goto(base+'/tests/batchReceiptHarness.html');await open();await waitText('Current synthetic scope denied')
  assert.equal(await page.locator('textarea').count(),0)
  assert.equal(await cancel().isDisabled(),false,'No pending operation: authorization rejection must allow closing')
  await cancel().focus();await page.keyboard.press('Enter');await page.getByRole('dialog').waitFor({state:'hidden'})
  if(red){results.push({width,initialDeniedCanClose:true});await context.close();continue}
  mode='balance-denied';await open();await page.locator('.el-form .el-select').first().click();await page.getByRole('option',{name:/PI-PRIVATE-ONE/}).click()
  await waitText('Current synthetic invoice hidden');assert.equal(await cancel().isDisabled(),false);await page.keyboard.press('Escape');await page.getByRole('dialog').waitFor({state:'hidden'})
  mode='draft';await open();await fill();mode='post-denied';await page.getByRole('button',{name:'创建回款单',exact:true}).click();await waitText('Current synthetic write denied')
  assert.equal(await cancel().isDisabled(),false);assert.equal(await page.locator('textarea').count(),0);await cancel().click();await page.getByRole('dialog').waitFor({state:'hidden'})
  mode='draft';await open();await fill();await submitUnknown();const original=writes.at(-1),before=writes.length
  assert.equal(await page.locator('textarea').isDisabled(),true);assert.equal(await page.getByRole('button',{name:'移除',exact:true}).count(),0)
  await page.keyboard.press('Escape');assert.equal(await page.getByRole('dialog').count(),1)
  await page.evaluate(()=>window.router.push('/other'));await tick();assert.match(page.url(),/batchReceiptHarness.html/)
  await inspect();await waitText('尚未查到原批次');assert.equal(writes.length,before);assert.deepEqual(queries.at(-1),original);assert.equal(await cancel().isDisabled(),true)
  mode='status-denied';await inspect();await waitText('Current synthetic recovery denied');assert.equal(await page.locator('textarea').count(),0);assert.equal(await cancel().isDisabled(),true)
  mode='unknown';await inspect();await waitText('尚未查到原批次');assert.equal(await page.locator('textarea').inputValue(),'ORIGINAL PRIVATE NOTE')
  await page.screenshot({path:output+'/pending-'+width+'.png',fullPage:true})
  const geometry=await page.getByRole('dialog').boundingBox();assert.ok(geometry.x>=0&&geometry.x+geometry.width<=width+1)
  assert.ok(geometry.y>=0&&geometry.y+geometry.height<=900+1,`Dialog footer must remain in viewport: ${JSON.stringify(geometry)}`)
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
  await page.evaluate(()=>window.forceClose());await page.getByRole('dialog').waitFor({state:'hidden'});await open();await waitText('尚未查到原批次');assert.deepEqual(queries.at(-1),original)
  await page.reload();await open();await waitText('尚未查到原批次');assert.deepEqual(queries.at(-1),original);assert.equal(writes.length,before)
  await page.evaluate(()=>window.changeActor(2));await page.getByRole('dialog').waitFor({state:'hidden'});mode='draft';await open()
  assert.equal(await page.locator('textarea').inputValue(),'');assert.equal(await page.getByText('ORIGINAL PRIVATE NOTE',{exact:true}).count(),0)
  await page.evaluate(()=>window.forceClose());await page.evaluate(()=>window.changeActor(1));mode='unknown';await open();await waitText('尚未查到原批次');assert.deepEqual(queries.at(-1),original)
  mode='held-status';hold=false;await inspect();await page.waitForFunction(()=>document.querySelector('[aria-busy=true]')!==null)
  while(!hold)await tick();assert.equal(heldKind,'status');const statusAborted=page.waitForEvent('requestfailed',{predicate:request=>request.url().endsWith('/batches/submission-status')});await page.evaluate(()=>window.changeActor(2));release();await heldTerminal;await statusAborted;await tick();assert.equal(await page.getByRole('dialog').count(),0);assert.equal(await page.evaluate(()=>window.saved.length),0)
  mode='bad-status';await page.evaluate(()=>window.changeActor(1));await open();await waitText('回执与原提交不一致');assert.equal(await cancel().isDisabled(),true);assert.equal(writes.length,before)
  mode='unknown';await inspect();await waitText('尚未查到原批次');mode='good';await page.getByRole('button',{name:'按原请求重试',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'})
  assert.deepEqual(writes.at(-1),original);assert.equal(await page.evaluate(()=>window.saved.length),1)
  mode='draft';committed=null;await open();await fill();const count=writes.length
  await page.evaluate(()=>{window.originalStorageSet=Storage.prototype.setItem;Storage.prototype.setItem=function(key,value){if(key.startsWith('ark_receipt_batch_pending_v1:'))throw new Error('Synthetic quota denial');return window.originalStorageSet.call(this,key,value)}})
  await page.getByRole('button',{name:'创建回款单',exact:true}).click();await waitText('原请求无法可靠保留');assert.equal(writes.length,count)
  await page.evaluate(()=>{Storage.prototype.setItem=window.originalStorageSet});await page.getByRole('button',{name:'重新读取恢复记录',exact:true}).click();await waitText('尚未查到原批次');mode='good';await page.getByRole('button',{name:'按原请求重试',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'})
  assert.equal(writes.length,count+1)
  mode='draft';committed=null;await open();await fill();mode='held-post';hold=false
  await page.getByRole('button',{name:'创建回款单',exact:true}).click();while(!hold)await tick();assert.equal(heldKind,'post')
  const heldOriginal=writes.at(-1),postAborted=page.waitForEvent('requestfailed',{predicate:request=>request.url().endsWith('/batches')});await page.evaluate(()=>window.changeActor(2));release();await heldTerminal;await postAborted;await tick();assert.equal(await page.getByRole('dialog').count(),0)
  assert.equal(await page.evaluate(()=>window.saved.length),2);mode='draft';await page.evaluate(()=>window.changeActor(1));await open();await page.getByRole('dialog').waitFor({state:'hidden'})
  assert.deepEqual(queries.at(-1),heldOriginal);assert.equal(await page.evaluate(()=>window.saved.length),3)
  assert.deepEqual(errors,[]);assert.deepEqual(unknown,[])
  results.push({width,scope:'Actual production Vue component and shared client; synthetic APIs and identity, not server authorization proof',initialDeniedClose:true,balanceDeniedClose:true,definitivePostDeniedClose:true,unknownFrozen:true,notFoundReadOnly:true,exactRetry:true,componentReopen:true,reload:true,actorIsolation:true,lateStatusIgnored:true,latePostIgnored:true,storageFailureNoPost:true,geometry:true,consoleErrors:errors,unexpectedEndpoints:unknown,cancelledTransportCount:cancelled.length})
  await context.close()
}
await writeFile(output+'/results.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results))
}finally{await browser.close()}
