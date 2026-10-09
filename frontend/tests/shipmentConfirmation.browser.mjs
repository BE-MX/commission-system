import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdir,writeFile} from 'node:fs/promises'
const require=createRequire(import.meta.url),{chromium}=require(process.argv[2]),base=process.argv[3],output=process.argv[4]
await mkdir(output,{recursive:true})
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true}),results=[]
const onlyConflict=process.argv[5]==='conflict'
const key='ark_shipment_confirmation_v1:1',reason='Review original funds and warehouse'
const safe=state=>({state,requires_review:false,blocks_confirmation:false,in_progress:false,attempt_count:state==='none'?0:1,unresolved_count:0,sent_rounds:state==='none'?0:1,message:''})
async function setup(width,previous='none') {
 const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'}),page=await context.newPage()
 const state={version:2,status:'pending_remote',previous,confirmation:safe(previous),review:'unknown',deny:false,wrongDetail:false,
    posts:[],reviews:[],errors:[],unexpected:[],reads:[],slotAtSend:[],confirmMode:'unknown',hold:null,showRow:true}
 const invoice={id:1,invoice_no:'PI-PRIVATE-ONE',currency:'USD',items:[{id:7,product_name:'Test product',quantity:10}]}
 const row=()=>({id:8,invoice_id:1,settlement_no:'S-ORIGINAL-CONFIRM',version:state.version,
    state:state.status==='shipped'?'shipped':state.status==='pending_remote'?'outbound_pending':'outbound_uncertain',
    quote:{items:[{invoice_item_id:7,quantity:4}]},balance:{goods_remaining:'0.00',freight_remaining:'0.00'},
    outbound:{id:9,status:state.status,number:'OUT-ORIGINAL',remote_id:'401',confirmation:{...state.confirmation}}})
 const other=()=>({...row(),id:18,invoice_id:2,version:state.version+1,settlement_no:'S-OTHER-BAD',outbound:{...row().outbound,id:19,remote_id:'402'}})
 page.on('pageerror',error=>state.errors.push(error.message));page.on('dialog',dialog=>dialog.accept())
 const ok=(route,data)=>route.fulfill({json:{code:200,message:'ok',data}})
 await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url())
    if(url.origin!==new URL(base).origin)return route.abort()
    if(!url.pathname.startsWith('/api/'))return route.continue()
    if(request.method()==='GET') {
      state.reads.push(url.pathname)
      if(state.deny)return route.fulfill({status:403,json:{detail:'Current original scope revoked'}})
      if(url.pathname==='/api/invoice/invoices/1')return ok(route,invoice)
      if(url.pathname==='/api/shipments/order/1')return ok(route,{items:state.showRow?[row()]:[]})
      if(url.pathname==='/api/shipments/8')return ok(route,state.wrongDetail?other():row())
    }
    if(request.method()==='POST' && url.pathname==='/api/invoices/1/shipment-quotes')return ok(route,{
      quote_hash:'a'.repeat(64),goods_amount:'40.00',packaging_amount:'0.00',handling_amount:'0.00',freight_amount:'0.00',deposit_applied:'0.00',new_payment_due:'40.00',is_final:false})
    if(request.method()==='POST' && url.pathname==='/api/shipments/8/confirm-outbound'){
      state.posts.push(request.postDataJSON());state.slotAtSend.push(await page.evaluate(k=>sessionStorage.getItem(k),key))
      if(state.confirmMode==='wrong')return ok(route,other())
      if(state.confirmMode==='hold'){
        await new Promise(resolve=>state.hold=resolve)
        state.holdCompleted=ok(route,{...row(),version:3,state:'shipped',outbound:{...row().outbound,status:'shipped',confirmation:safe('resolved')}})
        return state.holdCompleted
      }
      if(state.confirmMode==='success'){state.version++;state.status='shipped';state.confirmation=safe('resolved');return ok(route,row())}
      if(state.confirmMode==='uncertain'){state.version++;state.status='confirm_uncertain';state.confirmation={state:'unresolved',requires_review:true,blocks_confirmation:true,in_progress:false,message:'Original effect uncertain'};return ok(route,row())}
      return route.fulfill({status:503,json:{detail:'Original confirmation response unknown'}})
    }
    if(request.method()==='POST' && url.pathname==='/api/shipments/8/reconcile-outbound'){
      state.reviews.push(request.postDataJSON())
      if(state.review==='unknown')return route.fulfill({status:503,json:{detail:'Original review response unknown'}})
      if(state.review==='wrong')return ok(route,other())
      if(state.review==='stale')return ok(route,row())
      state.version++;state.confirmation=safe(previous);state.status='pending_remote';return ok(route,row())
    }
    state.unexpected.push(request.method()+' '+url.pathname);return route.fulfill({status:503,json:{detail:'Unexpected isolated endpoint'}})
 })
 await page.goto(base+'/tests/shipmentSubmissionHarness.html')
 const open=async()=>{await page.getByRole('button',{name:'打开出库结算',exact:true}).click();await page.getByRole('button',{name:'S-ORIGINAL-CONFIRM',exact:true}).waitFor()}
 const detail=async()=>{await page.getByRole('button',{name:'S-ORIGINAL-CONFIRM',exact:true}).click()}
 const confirm=async()=>{
    await page.getByRole('button',{name:'确认实际出库',exact:true}).click()
    const prompt=page.locator('.el-message-box');await prompt.locator('input').fill(reason)
    await prompt.getByRole('button',{name:'确认实际出库',exact:true}).click()
 }
 const review=async()=>{
    await page.getByRole('button',{name:'核对出库单',exact:true}).click()
    const prompt=page.locator('.el-message-box');await prompt.locator('input').fill('Check original provider note')
    await prompt.getByRole('button',{name:/^(确定|OK)$/,exact:true}).click()
 }
 const closed=async()=>{await page.getByRole('button',{name:'关闭',exact:true}).click();await page.locator('.el-dialog').waitFor({state:'detached'})}
 const slot=()=>page.evaluate(k=>sessionStorage.getItem(k),key)
 const idle=()=>page.waitForFunction(()=>document.querySelector('.shipment-content') && !document.querySelector('.shipment-content').getAttribute('aria-busy'))
 const blocked=async()=>{await idle();assert.equal(await page.getByRole('button',{name:'确认实际出库',exact:true}).count(),0);assert.equal(state.posts.length,1)}
 return {context,page,state,row,open,detail,confirm,review,closed,slot,idle,blocked}
}
try {
 for (const width of (onlyConflict?[]:[1440,390,320])) for (const previous of ['none','resolved']) {
    const c=await setup(width,previous),{page,state}=c
    try {
      await c.open();await c.confirm();await page.getByText('Original confirmation response unknown',{exact:true}).first().waitFor()
      await c.detail();await c.blocked();const original=await c.slot()
      assert.deepEqual(JSON.parse(original).command,{invoice_id:1,settlement_id:8,outbound_id:9,remote_id:'401',body:{version:2,reason}})
      assert.equal(state.slotAtSend[0],original)
      await c.closed();await c.open();await c.blocked();assert.equal(await c.slot(),original)
      await page.reload();await c.open();await c.blocked();assert.equal(await c.slot(),original)
      await c.closed();await page.evaluate(()=>window.changeInvoice(2));await c.open();await c.blocked()
      assert.equal(state.reads.includes('/api/invoice/invoices/2'),false)
      // A current-scope failure hides content but retains the original pending record.
      await c.closed();state.deny=true
      await page.getByRole('button',{name:'打开出库结算',exact:true}).click()
      await page.getByText('当前身份或订单授权需重新确认，原提交内容已隐藏。',{exact:true}).waitFor()
      assert.equal(await page.getByRole('button',{name:'S-ORIGINAL-CONFIRM',exact:true}).count(),0)
      assert.equal(await c.slot(),original)
      await c.closed();state.deny=false;await page.evaluate(()=>window.changeInvoice(1));await c.open();await c.blocked()
      state.review='unknown';await c.review();await page.getByText('Original review response unknown',{exact:true}).first().waitFor();await c.blocked();assert.equal(await c.slot(),original)
      state.review='stale';await c.review();await c.idle();await c.blocked();assert.equal(await c.slot(),original)
      state.review='wrong';await c.review();await page.getByText('核对回执与原出库单不一致，请保持原记录',{exact:true}).first().waitFor()
      await c.blocked();assert.equal(await c.slot(),original);assert.equal(await page.getByText('S-OTHER-BAD',{exact:true}).count(),0)
      state.wrongDetail=true;await c.detail();await page.getByText('详情与原结算不一致，请保持原记录核对',{exact:true}).first().waitFor()
      assert.equal(await page.getByText('S-OTHER-BAD',{exact:true}).count(),0);state.wrongDetail=false
      await c.detail();await c.blocked();assert.equal(await c.slot(),original)
      await page.getByRole('button',{name:'核对出库单',exact:true}).scrollIntoViewIfNeeded()
      await page.screenshot({path:output+'/unknown-'+previous+'-'+width+'.png',fullPage:true})
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
      state.review='success';await c.review();await page.getByRole('button',{name:'确认实际出库',exact:true}).waitFor();await c.idle()
      assert.equal(await c.slot(),null);assert.equal(state.version,3)
      state.confirmMode='success';await c.confirm();await c.idle();await page.getByText('已出库',{exact:true}).first().waitFor()
      assert.equal(await c.slot(),null);assert.equal(state.posts.length,2);assert.equal(state.posts[1].version,3)
      assert.deepEqual(state.errors,[]);assert.deepEqual(state.unexpected,[])
      results.push({width,previous,status:'passed',ordinaryGetCannotUnlock:true,closeReopenReload:true,originalInvoiceAfterPropSwitch:true,
        revokedScopeHides:true,unknownStaleWrongReviewRetains:true,wrongDetailNotRendered:true,explicitAdvancedReviewUnlocks:true,normalConfirmClears:true,
        scope:'Actual Vue/Chrome/storage/shared API; synthetic server and auth. Actual backend pre-START fencing is separately tested.'})
    } finally {await c.context.close()}
 }
 for (const width of (onlyConflict?[]:[1440,390,320])) for (const mode of ['active','expired','legacy','invalid','regression','missing']) {
    const c=await setup(width),{page,state}=c
    try {
      state.status=mode==='active'||mode==='expired'?'confirming':'pending_remote'
      state.confirmation=mode==='missing'?undefined:{state:mode==='active'?'active':mode==='expired'?'unresolved':mode==='legacy'?'legacy_review':mode==='regression'?'shipped_regression':'invalid',requires_review:true,blocks_confirmation:true,in_progress:mode==='active',message:'Original confirmation needs review'}
      // setup's row spread needs an explicit absent summary for the missing contract case.
      await c.open();await c.detail();await c.idle()
      assert.equal(await page.getByRole('button',{name:'确认实际出库',exact:true}).count(),0)
      assert.equal(await page.getByRole('button',{name:'核对出库单',exact:true}).count(),mode==='active'||mode==='missing'?0:1)
      assert.equal(state.posts.length,0);assert.deepEqual(state.errors,[]);assert.deepEqual(state.unexpected,[])
      results.push({width,mode,status:'passed',safeSummaryActions:true})
    } finally {await c.context.close()}
 }
 for (const mode of (onlyConflict?[]:['quota','drop','wrong','uncertain','late_actor'])) {
    const c=await setup(1440),{page,state}=c
    try {
      await c.open()
      if(mode==='quota'||mode==='drop')await page.evaluate(({key,mode})=>{
        const set=Storage.prototype.setItem
        Storage.prototype.setItem=function(name,value){if(name===key){if(mode==='quota')throw new Error('quota');return}return set.call(this,name,value)}
      },{key,mode})
      state.confirmMode=mode==='wrong'?'wrong':mode==='uncertain'?'uncertain':mode==='late_actor'?'hold':'unknown'
      if(mode==='late_actor')await page.evaluate(()=>{
        // Observe the actual XHR loadend task, then allow Axios/Vue promise chains
        // and rendering to finish. A fixed sleep can pass before the old response.
        window.originalConfirmationResponseProcessed=false
        const open=XMLHttpRequest.prototype.open,send=XMLHttpRequest.prototype.send
        XMLHttpRequest.prototype.open=function(method,url,...rest){this.__originalConfirm=method==='POST'&&String(url).endsWith('/shipments/8/confirm-outbound');return open.call(this,method,url,...rest)}
        XMLHttpRequest.prototype.send=function(...args){
          if(this.__originalConfirm)this.addEventListener('loadend',()=>setTimeout(()=>requestAnimationFrame(()=>requestAnimationFrame(()=>{window.originalConfirmationResponseProcessed=true})),0),{once:true})
          return send.apply(this,args)
        }
      })
      await c.confirm()
      if(mode==='quota'||mode==='drop'){
        await page.getByRole('status').filter({hasText:'当前身份或订单授权'}).waitFor()
        assert.equal(state.posts.length,0);assert.equal(await c.slot(),null)
      }else if(mode==='late_actor'){
        await page.waitForFunction(k=>sessionStorage.getItem(k)!=null,key)
        // wait on a confirmed route handle rather than guessing server delay.
        const deadline=Date.now()+5000
        while(!state.hold && Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,20))
        assert.equal(typeof state.hold,'function','Original route never entered its controlled gate')
        const original=await c.slot();await page.evaluate(()=>window.changeActor(2));await page.locator('.el-dialog').waitFor({state:'detached'})
        const responsePromise=page.waitForResponse(response=>response.request().method()==='POST'&&new URL(response.url()).pathname==='/api/shipments/8/confirm-outbound')
        state.hold()
        const response=await responsePromise
        assert.equal(response.status(),200);assert.equal(await response.finished(),null)
        assert.ok(state.holdCompleted,'The held route must have actually fulfilled')
        await state.holdCompleted
        await page.waitForFunction(()=>window.originalConfirmationResponseProcessed===true)
        assert.equal(await c.slot(),original);assert.equal(await page.locator('.el-dialog').count(),0)
        await page.evaluate(()=>window.changeActor(1));await c.open();await c.blocked();assert.equal(await c.slot(),original)
      }else{
        await c.idle();await c.blocked();assert.notEqual(await c.slot(),null)
        assert.equal(await page.getByText('S-OTHER-BAD',{exact:true}).count(),0)
      }
      assert.deepEqual(state.errors,[]);assert.deepEqual(state.unexpected,[])
      results.push({width:1440,mode,status:'passed',storageOrReceiptBoundary:true})
    } finally {state.hold?.();await c.context.close()}
 }
 {
    const c=await setup(1440),{page,state}=c
    try {
      state.showRow=false
      await page.getByRole('button',{name:'打开出库结算',exact:true}).click()
      await page.locator('.el-table input').first().fill('4')
      await page.locator('.el-table input').first().blur()
      await page.getByRole('button',{name:'核算本批金额',exact:true}).click()
      await page.getByRole('button',{name:'生成本批结算单',exact:true}).waitFor()
      const original=JSON.stringify({actor:1,command:{invoice_id:1,settlement_id:8,outbound_id:9,remote_id:'401',body:{version:2,reason}}})
      await page.evaluate(({key,original})=>sessionStorage.setItem(key,original),{key,original})
      await page.getByRole('button',{name:'生成本批结算单',exact:true}).click()
      await page.waitForFunction(()=>document.querySelector('.el-dialog__title')?.textContent.includes('核对原'))
      await c.idle();await page.screenshot({path:output+'/late-slot-conflict.png',fullPage:true})
      assert.equal(await page.getByRole('button',{name:'关闭',exact:true}).isEnabled(),true,'uninvoked fresh create must not trap original confirmation recovery')
      await page.getByRole('button',{name:'核对出库单',exact:true}).waitFor()
      assert.equal(await page.getByRole('button',{name:'按原请求重试',exact:true}).count(),0)
      assert.equal(await page.evaluate(()=>sessionStorage.getItem('ark_shipment_pending_v1:1')),null)
      assert.equal(await c.slot(),original);assert.equal(state.posts.length,0)
      assert.deepEqual(state.errors,[]);assert.deepEqual(state.unexpected,[])
      await c.closed();results.push({width:1440,mode:'late_slot_conflict',status:'passed',uninvokedCreateDiscarded:true,originalConfirmationAccessible:true,noNewFinancialSubmission:true})
    } finally {await c.context.close()}
 }
 await writeFile(output+'/results.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results))
}finally{await browser.close()}
