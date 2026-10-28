import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
import { mkdir } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_ADMIN_ORIGIN || 'http://127.0.0.1:3026'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/)
const output = process.env.PORTAL_QA_OUTPUT || '../tmp/portal-customer-settings/admin'
await mkdir(output, { recursive: true })
const id = n => `${String(n).padStart(8, '0')}-1111-4111-8111-111111111111`
const customers = [1,2].map(n => ({ id:id(n), company_display_name:`Synthetic ${n}`, canonical_customer_id:String(n), sales_user_id:'5', row_version:3, status:'enabled', capabilities:{can_view_price:true, can_order:true}, catalog_version:7, mapping_version:1, catalog_item_ids:[id(3),id(4)], accounts:{items:[],total:0} }))
for (const width of [1440,390]) {
  const browser = await chromium.launch({headless:true,executablePath:process.env.PORTAL_CHROMIUM})
  const context = await browser.newContext({viewport:{width,height:1000}})
  const page = await context.newPage(), errors = [], writes = [], reads = []
  let lose = false, delay = false, delayed, release
  const gate = new Promise(resolve => { release=resolve })
  const delivery = n => ({contact_name:`Buyer ${n}`,phone:'123456',address_line1:`Existing address ${n}`,address_line2:'',city:'Paris',region:'',postal_code:'',country_code:'FR'})
  const saved = {1:delivery(1),2:delivery(2)}, versions = {1:5,2:7}
  await context.addInitScript(() => {localStorage.setItem('ark_access_token','synthetic-test-only');sessionStorage.setItem('leshine_welcome_shown_session','1')})
  page.on('pageerror',e=>errors.push(e.message))
  await context.route('**/api/**',async route=>{
    const req=route.request(),path=new URL(req.url()).pathname
    const send=(data,status=200)=>route.fulfill({status,json:{code:status,message:'ok',data}})
    if(path==='/api/auth/me')return route.fulfill({json:{id:5,name:'Synthetic Sales',roles:[],permissions:['portal_access:read','portal_access:admin']}})
    if(path==='/api/auth/refresh')return route.fulfill({json:{access_token:'synthetic-test-only'}})
    if(path==='/api/portal/admin/v1/customers')return send({items:customers,total:2})
    const match=path.match(/\/customers\/([^/]+)(?:\/(delivery|prices))?$/)
    if(match){
      const n=customers.findIndex(c=>c.id===match[1])+1,section=match[2]
      if(!section)return send(customers[n-1])
      if(req.method()==='PUT'){
        writes.push({n,section,body:req.postDataJSON(),version:req.headers()['if-match']})
        if(section==='delivery'){assert.equal(req.headers()['if-match'],`"${versions[n]}"`);saved[n]=req.postDataJSON().delivery;versions[n]++}
        if(lose){lose=false;return route.abort('failed')}
        return send({row_version:versions[n]})
      }
      reads.push({n,section})
      if(delay&&n===1&&section==='delivery'){delay=false;delayed=true;await gate;try{return await send({delivery:delivery(1),row_version:5})}catch{return}}
      if(section==='delivery')return send({delivery:saved[n],row_version:versions[n]})
      return send({row_version:3,items:[{id:id(3),model_name:'Genius',color_name:'#2B',length:'20',standard_price:'25.0000',unit_price:null},{id:id(4),model_name:'Tape',color_name:'#60',length:'18',standard_price:'8.0000',unit_price:'7.5000'}]})
    }
    return send({})
  })
  const dialog=()=>page.locator('.portal-customer-settings:visible')
  const manage=async n=>{await page.locator(`button[data-portal-access="${id(n)}"]`).click();await page.getByRole('button',{name:'客户地址',exact:true}).waitFor()}
  const open=async section=>{await page.getByRole('button',{name:section==='delivery'?'客户地址':'商品价格',exact:true}).click();await dialog().waitFor()}
  const close=async()=>{await dialog().getByRole('button',{name:'关闭',exact:true}).click();await dialog().waitFor({state:'hidden'})}
  try{
    await page.goto(origin+'/portal/customers');await manage(1);await open('delivery')
    await dialog().getByLabel('联系人',{exact:true}).waitFor()
    assert.equal(await dialog().getByLabel('地址',{exact:true}).inputValue(),'Existing address 1')
    await dialog().getByLabel('地址',{exact:true}).fill('Updated customer address')
    await dialog().getByRole('button',{name:'保存',exact:true}).click();await dialog().waitFor({state:'hidden'})
    assert.equal(writes[0].version,'"5"');assert.equal(writes[0].body.delivery.address_line1,'Updated customer address')
    await open('prices');await dialog().getByLabel('Genius #2B 客户单价',{exact:true}).waitFor()
    assert.equal(await dialog().getByLabel('Genius #2B 客户单价',{exact:true}).inputValue(),'25.0000')
    assert.equal(await dialog().getByLabel('Tape #60 客户单价',{exact:true}).inputValue(),'7.5000')
    await dialog().locator('.el-table__header-wrapper .el-checkbox').click()
    await dialog().getByLabel('批量单价',{exact:true}).fill('19.25')
    await dialog().getByRole('button',{name:'应用到所选 2 项',exact:true}).click()
    assert.equal(await dialog().getByLabel('Genius #2B 客户单价',{exact:true}).inputValue(),'19.25')
    assert.ok(await dialog().evaluate(el=>el.getBoundingClientRect().left>=0&&el.getBoundingClientRect().right<=innerWidth+1))
    await page.screenshot({path:`${output}/prices-${width}.png`,fullPage:true})
    await dialog().getByRole('button',{name:'保存',exact:true}).click();await dialog().waitFor({state:'hidden'})
    assert.equal(writes[1].version,'"3"');assert.deepEqual(writes[1].body,{items:[{item_id:id(3),unit_price:'19.2500'},{item_id:id(4),unit_price:'19.2500'}]})
    await open('delivery');await dialog().getByLabel('地址',{exact:true}).fill('Committed despite response loss');lose=true
    await dialog().getByRole('button',{name:'保存',exact:true}).click();await dialog().getByText('保存结果未确认，请读取当前资料核对后再编辑。',{exact:true}).waitFor()
    assert.equal(await dialog().getByRole('button',{name:'保存',exact:true}).isDisabled(),true)
    assert.equal(await dialog().getByLabel('地址',{exact:true}).isDisabled(),true)
    const count=writes.length, readCount=reads.length
    await dialog().getByRole('button',{name:'读取当前资料',exact:true}).click()
    await dialog().getByLabel('地址',{exact:true}).waitFor()
    assert.equal(await dialog().getByLabel('地址',{exact:true}).inputValue(),'Committed despite response loss')
    assert.equal(writes.length,count);assert.equal(reads.length,readCount+1)
    await page.screenshot({path:`${output}/delivery-${width}.png`,fullPage:true})
    await close();delay=true;await open('delivery')
    await page.waitForFunction(()=>Boolean(document.querySelector('.portal-customer-settings .el-loading-mask')))
    assert.equal(delayed,true)
    await page.goto(origin+'/portal/customers');await manage(2);await open('delivery');await dialog().getByLabel('联系人',{exact:true}).waitFor()
    assert.equal(await dialog().getByLabel('地址',{exact:true}).inputValue(),'Existing address 2')
    release();await page.waitForTimeout(150)
    assert.equal(await dialog().getByLabel('地址',{exact:true}).inputValue(),'Existing address 2')
    assert.deepEqual(errors,[])
    console.log(JSON.stringify({width,status:'pass',simulatedWrites:writes.length,checks:['existing address','version header','atomic batch','uncertain GET only','cross customer late response']}))
  }catch(e){await page.screenshot({path:`${output}/failure-${width}.png`,fullPage:true});console.log((await page.locator('body').innerText()).slice(-3000));throw e}finally{release();await browser.close()}
}
