import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdir,writeFile} from 'node:fs/promises'
const require=createRequire(import.meta.url),{chromium}=require(process.argv[2]),base=process.argv[3],output=process.argv[4],red=process.argv[5]==='--red-close'
await mkdir(output,{recursive:true})
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true}),results=[]
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aO6sAAAAASUVORK5CYII=','base64')
try { for(const width of red?[1440]:[1440,390,320]) {
 const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'}),page=await context.newPage(),errors=[],writes=[],queries=[],unexpected=[]
 let mode='draft',committed=null,hold=false,release,heldTerminal,settleHeld
 page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept())
 const invoice={id:1,invoice_no:'PI-PRIVATE-ONE',currency:'USD',items:[{id:7,product_name:'PRIVATE PRODUCT',model:'Original model',color:'Original color',length:'20',quantity:10}]}
 const receipt=body=>({id:8,invoice_id:1,request_key:body.request_key,quote_hash:body.quote_hash,version:1,settlement_no:'S-ORIGINAL',state:'awaiting_payment',quote:{new_payment_due:'80'}})
 const ok=(route,data)=>route.fulfill({json:{code:200,message:'ok',data}})
 await page.route(base+'/api/**',async route=>{
  const request=route.request(),path=new URL(request.url()).pathname
  if(/^\/api\/invoice\/invoices\/[12]$/.test(path))return ok(route,invoice)
  if(/^\/api\/shipments\/order\/[12]$/.test(path))return ok(route,{items:[]})
  if(path==='/api/invoices/1/shipment-quotes')return ok(route,{quote_hash:'a'.repeat(64),goods_amount:'80',packaging_amount:'0',handling_amount:'0',freight_amount:'20',deposit_applied:'0',new_payment_due:'100',is_final:false})
  if(path==='/api/receipts/types')return ok(route,['T/T'])
  if(path==='/api/receipts/attachments'&&request.method()==='POST')return ok(route,{id:'synthetic-proof',name:'payment.png'})
  if(path==='/api/receipts/attachments/synthetic-proof')return route.fulfill({contentType:'image/png',body:png})
  if(path==='/api/invoices/1/shipment-settlements'){
   const body=request.postDataJSON(),captured=mode;writes.push({path,body})
   if(captured==='held-post'){heldTerminal=new Promise(r=>settleHeld=r);hold=true;await new Promise(r=>release=r)}
   if(captured==='retry-denied')return route.fulfill({status:409,json:{detail:'Synthetic original quote stale'}})
   if(captured==='post-denied')return route.fulfill({status:403,json:{detail:'Synthetic current write denied'}})
   if(captured==='unknown')return route.fulfill({status:503,json:{detail:'Synthetic original result unknown'}})
   if(captured==='malformed')return ok(route,{...receipt(body),invoice_id:2})
   committed=body
   try{return await ok(route,receipt(body))}catch(e){if(captured!=='held-post')throw e}finally{if(captured==='held-post')settleHeld()}
  }
  if(path==='/api/invoices/1/shipment-settlements/submission-status'){
   const body=request.postDataJSON(),captured=mode;queries.push({path,body})
   if(captured==='held-status'){heldTerminal=new Promise(r=>settleHeld=r);hold=true;await new Promise(r=>release=r)}
   if(captured==='status-denied')return route.fulfill({status:403,json:{detail:'Synthetic current recovery denied'}})
   if(captured==='bad-status')return ok(route,{state:'found',request_key:body.request_key,invoice,settlement:{...receipt(body),request_key:'wrong'}})
   const result=committed?.request_key===body.request_key?{state:'found',request_key:body.request_key,invoice,settlement:receipt(body)}:{state:'not_found',request_key:body.request_key,invoice:{...invoice,items:invoice.items.map(row=>({...row,quantity:body.items.find(i=>i.invoice_item_id===row.id)?.quantity}))}}
   try{return await ok(route,result)}catch(e){if(captured!=='held-status')throw e}finally{if(captured==='held-status')settleHeld()}
  }
  unexpected.push(path);return route.fulfill({status:503,json:{detail:'Unexpected isolated endpoint'}})
 })
 const open=()=>page.getByRole('button',{name:'打开出库结算',exact:true}).click(),close=()=>page.getByRole('button',{name:'关闭',exact:true}),inspect=()=>page.getByRole('button',{name:'核对原提交（只查询）',exact:true}).click()
 const waitText=text=>page.getByText(text,{exact:false}).first().waitFor(),tick=()=>page.evaluate(()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r))))
 async function fill(){await page.locator('.el-table').getByRole('spinbutton').fill('4');await page.keyboard.press('Tab');await page.locator('.el-form-item').filter({hasText:'本批运费'}).getByRole('spinbutton').fill('20');await page.keyboard.press('Tab');await page.getByRole('button',{name:'核算本批金额',exact:true}).click();await waitText('部分出库');if(!await page.getByRole('checkbox',{name:'同时登记本次实际回款'}).isChecked())await page.locator('label.el-checkbox').filter({hasText:'同时登记本次实际回款'}).click();await page.locator('.fields-grid .el-form-item').filter({hasText:'本次回款金额'}).getByRole('spinbutton').fill('32');await page.keyboard.press('Tab');await page.locator('.fields-grid .el-select').getByRole('combobox').focus();await page.keyboard.press('ArrowDown');try{await page.getByRole('option',{name:'T/T',exact:true}).click()}catch(e){await page.screenshot({path:output+'/failed-'+width+'.png',fullPage:true});await writeFile(output+'/failed-'+width+'.html',await page.content());throw e};await page.locator('input[type=file]').setInputFiles({name:'payment.png',mimeType:'image/png',buffer:png});await page.locator('textarea').fill('ORIGINAL PRIVATE NOTE')}
 async function send(){await page.getByRole('button',{name:'生成本批结算单',exact:true}).click()}
 await page.goto(base+'/tests/shipmentSubmissionHarness.html');await open();await fill();mode='unknown';await send();await waitText('Synthetic original result unknown')
 const original=writes.at(-1),before=writes.length
 assert.equal(await page.locator('textarea').count(),0);assert.equal(await page.getByRole('spinbutton').count(),0)
 mode='status-denied';await inspect();await waitText('Synthetic current recovery denied')
 assert.equal(await close().isDisabled(),false,'Persisted unknown must permit safe exit after current authorization denial')
 await close().click();await page.getByRole('dialog').waitFor({state:'hidden'});assert.equal(writes.length,before)
 assert.deepEqual(await page.evaluate(()=>JSON.parse(sessionStorage.getItem('ark_shipment_pending_v1:1')).body),original.body)
 if(red){results.push({width,persistedUnknownCanClose:true});await context.close();continue}
 mode='unknown';await page.evaluate(()=>window.changeInvoice(2));await open();await waitText('尚未查到原结算');assert.deepEqual(queries.at(-1).body,original.body);assert.match(queries.at(-1).path,/invoices\/1\//)
 assert.equal(await page.getByRole('spinbutton').count(),0);assert.equal(await page.locator('textarea').count(),0);assert.equal(writes.length,before)
 await tick();await page.screenshot({path:output+'/pending-'+width+'.png',fullPage:true})
 const geometry=await page.getByRole('dialog').boundingBox();assert.ok(geometry.x>=0&&geometry.x+geometry.width<=width+1);assert.ok(geometry.y>=0&&geometry.y+geometry.height<=901,JSON.stringify(geometry));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
 await page.evaluate(()=>window.router.push('/other'));await page.getByText('Other page',{exact:true}).waitFor();assert.equal(writes.length,before)
 await page.evaluate(()=>window.router.push('/tests/shipmentSubmissionHarness.html'));await open();await waitText('尚未查到原结算');assert.deepEqual(queries.at(-1).body,original.body)
 await page.reload();await open();await waitText('尚未查到原结算');assert.equal(writes.length,before);assert.deepEqual(queries.at(-1).body,original.body)
 await page.evaluate(()=>window.changeActor(2));await page.getByRole('dialog').waitFor({state:'hidden'});mode='draft';await open();await page.getByText('PRIVATE PRODUCT',{exact:false}).first().waitFor();assert.equal(await page.locator('textarea').count(),0)
 await page.evaluate(()=>window.forceClose());await page.evaluate(()=>window.changeActor(1));mode='unknown';await open();await waitText('尚未查到原结算')
 mode='held-status';hold=false;await inspect();while(!hold)await tick();assert.equal(await close().isDisabled(),true)
 const aborted=page.waitForEvent('requestfailed',{predicate:r=>r.url().endsWith('/submission-status')});await page.evaluate(()=>window.changeActor(2));release();await heldTerminal;await aborted;await tick();assert.equal(await page.getByRole('dialog').count(),0);assert.equal(await page.evaluate(()=>window.saved.length),0)
 mode='bad-status';await page.evaluate(()=>window.changeActor(1));await open();await waitText('回执与原发货提交不一致');assert.equal(writes.length,before)
 mode='unknown';await inspect();await waitText('尚未查到原结算');mode='retry-denied';await page.getByRole('button',{name:'按原请求重试',exact:true}).click();await waitText('Synthetic original quote stale');assert.deepEqual(writes.at(-1),original);assert.deepEqual(await page.evaluate(()=>JSON.parse(sessionStorage.getItem('ark_shipment_pending_v1:1')).body),original.body);assert.equal(await page.getByRole('spinbutton').count(),0);mode='unknown';await inspect();await waitText('尚未查到原结算');mode='good';await page.getByRole('button',{name:'按原请求重试',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});assert.deepEqual(writes.at(-1),original);assert.equal(await page.evaluate(()=>window.saved.length),1)
 mode='draft';committed=null;await open();await fill();mode='post-denied';await send();await waitText('Synthetic current write denied');assert.equal(await close().isDisabled(),false);assert.equal(await page.locator('textarea').count(),0);await close().click();await page.getByRole('dialog').waitFor({state:'hidden'})
 mode='draft';await open();await fill();const count=writes.length
 await page.evaluate(()=>{window.originalStorageSet=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k.startsWith('ark_shipment_pending_v1:'))throw Error('Synthetic quota denial');return window.originalStorageSet.call(this,k,v)}})
 await send();await waitText('原请求无法可靠保留');assert.equal(writes.length,count)
 await page.evaluate(()=>Storage.prototype.setItem=window.originalStorageSet);await page.getByRole('button',{name:'重新读取恢复记录',exact:true}).click();await waitText('尚未查到原结算');mode='retry-denied';await page.getByRole('button',{name:'按原请求重试',exact:true}).click();await waitText('Synthetic original quote stale');assert.equal(await page.evaluate(()=>sessionStorage.getItem('ark_shipment_pending_v1:1')),null,'A definitely never-sent original first actual POST409 must not become permanent unknown');await page.getByRole('button',{name:'核算本批金额',exact:true}).waitFor();mode='draft';await fill();mode='good';await send();await page.getByRole('dialog').waitFor({state:'hidden'});assert.equal(writes.length,count+2)
 mode='draft';committed=null;await open();await fill();mode='held-post';hold=false;await send();while(!hold)await tick();assert.equal(await close().isDisabled(),true)
 const heldOriginal=writes.at(-1),postAborted=page.waitForEvent('requestfailed',{predicate:r=>r.url().endsWith('/shipment-settlements')});await page.evaluate(()=>window.changeActor(2));release();await heldTerminal;await postAborted;await tick();assert.equal(await page.getByRole('dialog').count(),0);assert.equal(await page.evaluate(()=>window.saved.length),2)
 await page.evaluate(()=>window.changeActor(1));mode='good';await open();await page.getByRole('dialog').waitFor({state:'hidden'});assert.deepEqual(queries.at(-1).body,heldOriginal.body);assert.equal(await page.evaluate(()=>window.saved.length),3)
 assert.deepEqual(errors,[]);assert.deepEqual(unexpected,[])
 results.push({width,scope:'Production Vue/shared client/router/sessionStorage/AbortController; synthetic APIs and auth, not backend authority proof',persistedUnknownSafeExit:true,originalInvoiceRecovery:true,frozen:true,notFoundNoWrite:true,exactRetry:true,reload:true,routeLeaveAndReopen:true,actorIsolation:true,lateStatusIgnored:true,latePostIgnored:true,definitiveRejectCanClose:true,storageFailureNoPost:true,neverSentDefinitiveRejectRecoverable:true,unknownDefinitiveRejectFrozen:true,geometry:true,consoleErrors:errors,unexpectedEndpoints:unexpected})
 await context.close()
} await writeFile(output+'/results.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results)) }finally{await browser.close()}
