import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const require=createRequire(import.meta.url), {chromium}=require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin=process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3210'
assert.match(origin,/^http:\/\/127\.0\.0\.1:\d+$/)
const output=process.env.PORTAL_QA_OUTPUT || 'tmp/browser-qa';await mkdir(output,{recursive:true})
const browser=await chromium.launch({headless:true,...(process.env.PORTAL_CHROMIUM?{executablePath:process.env.PORTAL_CHROMIUM}:{})})
const context=await browser.newContext({viewport:{width:1440,height:1000}}), errors=[],calls=[]
const id='11111111-1111-4111-8111-111111111111',account='99999999-1111-4111-8111-111111111111',other='88888888-1111-4111-8111-111111111111'
let activeAccount=account,mode='missing',savedReceipt,locator
const reason='Please cancel: private buyer note 😀',slot='leshine.portal.action:'+account
const order={request_id:id,request_no:'REQ-REFRESH-001',status:'submitted',row_version:1,available_actions:['cancel'],submitted_at:'2026-10-01T10:00:00',currency:'USD',product_amount:'64.00',total_amount:null,fees:{status:'pending'},items:[],delivery:{country_code:'GB'},customer_safe_timeline:[]}
await context.route('**/api/portal/v1/**',async route=>{
 const request=route.request(),url=new URL(request.url()),path=url.pathname,body=request.postDataJSON();calls.push({path,method:request.method(),body})
 const send=(data,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify({code:status,message:'OK',data})})
 if(path.endsWith('/session'))return send({me:{account_public_id:activeAccount,company_display_name:'Synthetic partner'},capabilities:{view_catalog:true,view_price:true,place_order:true},csrf_token:'synthetic-csrf'})
 if(path.endsWith('/sales-contact'))return send({contact:null})
 if(path.endsWith('/catalog'))return send({items:[],total:0})
 if(path.endsWith('/orders'))return send({items:[order],total:1,page:1,page_size:20})
 if(path.endsWith('/cancel')){
  assert.equal(body.reason,reason);assert.equal(request.headers()['if-match'],'"1"')
  order.status='cancelled';order.row_version=2;order.available_actions=[]
  savedReceipt={replayed:true,original_receipt:{request_id:id,status:'cancelled',row_version:2},current_state:'cancelled',row_version:2}
  locator={request_id:id,action:'cancel',payload_hash:createHash('sha256').update(JSON.stringify({hash_schema:1,payload:body})).digest('hex')}
  return route.abort('failed')
 }
 if(path.endsWith('/action-receipt')){
  assert.equal(request.method(),'GET');assert.equal(request.postData(),null)
  assert.deepEqual(Object.fromEntries(url.searchParams),{action:'cancel',payload_hash:locator.payload_hash})
  if(mode==='missing')return send({found:false,command:locator})
  if(mode==='mismatch')return send({found:true,command:{...locator,payload_hash:'a'.repeat(64)},receipt:savedReceipt})
  return send({found:true,command:locator,receipt:savedReceipt})
 }
 if(path.endsWith('/orders/'+id))return send(order)
 throw Error('Unexpected '+path)
})
const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message))
try{
 await page.goto(origin+'/orders/'+id);await page.getByRole('button',{name:'Cancel this request'}).click()
 const dialog=page.getByRole('dialog');await dialog.getByLabel('Reason for cancelling').fill('\u0085'+reason+'\u0085')
 await dialog.getByRole('button',{name:'Cancel request',exact:true}).click()
 await page.getByRole('heading',{name:'The action result needs confirmation.'}).waitFor()
 const raw=await page.evaluate(slot=>sessionStorage.getItem(slot),slot)
 assert.ok(raw);assert.ok(!raw.includes(reason));assert.ok(!raw.includes('REQ-REFRESH'));assert.equal(JSON.parse(raw).payload_hash,locator.payload_hash)
 await page.reload();await page.getByRole('heading',{name:'The action result needs confirmation.'}).waitFor()
 assert.equal(await page.getByRole('button',{name:'Retry original action'}).count(),0)
 assert.equal(calls.filter(c=>c.method==='POST').length,1)
 const statusResponse=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/orders/'+id)&&r.request().method()==='GET')
 await page.getByRole('button',{name:'Check original action receipt'}).click();await(await statusResponse).finished()
 await page.getByRole('heading',{name:'The action result needs confirmation.'}).waitFor()
 assert.match(await page.locator('.order-command-notice').innerText(),/Latest request status: Cancelled/)
 assert.equal(await page.locator('.session-notice').filter({hasText:'Original action on'}).count(),0)
 mode='mismatch';const badResponse=page.waitForResponse(r=>new URL(r.url()).pathname.endsWith('/action-receipt'))
 await page.getByRole('button',{name:'Check original action receipt'}).click();await(await badResponse).finished()
 await page.getByRole('heading',{name:'The action result needs confirmation.'}).waitFor()
 assert.equal(await page.locator('.session-notice').filter({hasText:'Original action on'}).count(),0)
 for(const width of [1440,390,320]){await page.setViewportSize({width,height:1000});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:output+'/refresh-unknown-'+width+'.png',fullPage:true})}
 activeAccount=other;await page.reload();await page.getByRole('heading',{name:'Your order request.'}).waitFor()
 assert.equal(await page.locator('.order-command-notice').count(),0);assert.equal(await page.evaluate(slot=>sessionStorage.getItem(slot),slot),raw)
 activeAccount=account;mode='found';await page.reload();await page.getByRole('button',{name:'Check original action receipt'}).click()
 await page.getByText(/Original action on .* was recorded/).waitFor()
 assert.equal(await page.evaluate(slot=>sessionStorage.getItem(slot),slot),null);assert.equal(calls.filter(c=>c.method==='POST').length,1)
 await page.evaluate(slot=>sessionStorage.setItem(slot,'{"reason":"PRIVATE_CORRUPT_PAYLOAD"}'),slot);await page.reload()
 await page.getByRole('alert').filter({hasText:'Your previous action reference could not be verified.'}).waitFor()
 assert.equal(await page.getByRole('heading',{name:'Your order request.'}).count(),1)
 assert.ok(!(await page.locator('body').innerText()).includes('PRIVATE_CORRUPT_PAYLOAD'))
 await page.getByRole('button',{name:'View existing requests',exact:true}).click();await page.getByRole('heading',{name:'Your requests.'}).waitFor()
 assert.equal(await page.evaluate(slot=>sessionStorage.getItem(slot),slot),'{"reason":"PRIVATE_CORRUPT_PAYLOAD"}')
 assert.deepEqual(errors,[]);assert.equal(calls.filter(c=>c.method==='POST').length,1)
 await writeFile(output+'/report.json',JSON.stringify({source:'actual Chromium current bundle, intercepted synthetic API',calls:calls.length,posts:1,widths:[1440,390,320],scenarios:['lost committed response','refresh GET only','missing receipt stays unknown','wrong hash stays unknown','other account marker hidden','original receipt confirmed','corrupt marker preserves session']},null,2))
 console.log(JSON.stringify({passed:true,calls:calls.length,posts:1}))
}finally{await context.close();await browser.close()}
