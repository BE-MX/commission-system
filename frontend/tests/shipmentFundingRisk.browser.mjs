import assert from 'node:assert/strict'
import {createRequire} from 'node:module'
import {mkdir,writeFile} from 'node:fs/promises'
const require=createRequire(import.meta.url),{chromium}=require(process.argv[2]),base=process.argv[3],output=process.argv[4]
await mkdir(output,{recursive:true})
const browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true}),results=[]
try {for (const width of [1440,390,320]) {
 const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'}),page=await context.newPage(),errors=[],writes=[],unexpected=[]
 let valid=false
 const reason='本批关联回款已失效，余额暂不可计算，请核对原单'
 const invoice={id:1,invoice_no:'PI-PRIVATE-ONE',currency:'USD',items:[{id:7,product_name:'Test product',quantity:10}]}
 const row=()=>({id:8,invoice_id:1,settlement_no:'S-ORIGINAL-RISK',version:2,state:valid?'shipped':'outbound_uncertain',
    quote:{items:[{invoice_item_id:7,quantity:4}]},balance:valid?{goods_remaining:'26.00',freight_remaining:'0.00'}:null,
    ...(valid?{}:{balance_error:reason}),outbound:{id:9,status:valid?'shipped':'shipped_unfunded',number:'OUT-ORIGINAL',remote_id:'401',
    last_error:valid?null:'小满已实际出库，但关联回款未通过实时核验，请立即核查'}})
 page.on('pageerror',error=>errors.push(error.message))
 const ok=(route,data)=>route.fulfill({json:{code:200,message:'ok',data}})
 await page.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url())
    if(url.origin!==new URL(base).origin)return route.abort()
    if(!url.pathname.startsWith('/api/'))return route.continue()
    if(request.method()!=='GET'){writes.push(url.pathname);return route.fulfill({status:503,json:{detail:'Unexpected financial write'}})}
    if(url.pathname==='/api/invoice/invoices/1')return ok(route,invoice)
    if(url.pathname==='/api/shipments/order/1')return ok(route,{items:[row()]})
    if(url.pathname==='/api/shipments/8')return ok(route,row())
    unexpected.push(url.pathname);return route.fulfill({status:503,json:{detail:'Unexpected isolated endpoint'}})
 })
 await page.goto(base+'/tests/shipmentSubmissionHarness.html')
 await page.getByRole('button',{name:'打开出库结算',exact:true}).click()
 const detail=()=>page.getByRole('button',{name:'S-ORIGINAL-RISK',exact:true}).click()
 await detail();await page.getByText(reason,{exact:true}).waitFor()
 const content=()=>page.locator('.el-descriptions').filter({hasText:'S-ORIGINAL-RISK'})
 assert.equal(await content().getByText('待核对',{exact:true}).count(),2)
 assert.equal(await content().getByText('0.00',{exact:true}).count(),0)
 assert.equal(await page.getByRole('button',{name:'确认实际出库',exact:true}).count(),0)
 assert.equal(await page.getByRole('button',{name:'核对出库单',exact:true}).count(),1)
 await page.getByText(reason,{exact:true}).scrollIntoViewIfNeeded()
 await page.screenshot({path:output+'/risk-'+width+'.png',fullPage:true})
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false)
 valid=true;await detail();await content().getByText('26.00',{exact:true}).waitFor()
 assert.equal(await content().getByText('0.00',{exact:true}).count(),1)
 assert.equal(await page.getByText(reason,{exact:true}).count(),0)
 assert.equal(await content().getByText('待核对',{exact:true}).count(),0)
 assert.deepEqual(errors,[]);assert.deepEqual(writes,[]);assert.deepEqual(unexpected,[])
 results.push({width,unavailableShownAsPending:true,noFictitiousZero:true,normalMoneyStillShown:true,noFinancialWrites:true,
    noPageErrors:true,scope:'Actual Vue and shared client on isolated harness; synthetic API/auth, not backend authorization or shipment proof'})
 await context.close()
}await writeFile(output+'/results.json',JSON.stringify(results,null,2));console.log(JSON.stringify(results))}finally{await browser.close()}
