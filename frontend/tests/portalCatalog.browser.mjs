import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require=createRequire(import.meta.url),{chromium}=require(process.env.PORTAL_PLAYWRIGHT_MODULE||'playwright')
const browser=await chromium.launch({executablePath:process.env.PORTAL_CHROMIUM,headless:true}),context=await browser.newContext({viewport:{width:1440,height:1050}}),page=await context.newPage()
const id='11111111-1111-4111-8111-111111111111',fingerprint='a'.repeat(64)
const standard={product_name:'Standard Hair',model:'ST',color:'Black',length:'20',weight:'20g'}
let item=null,mode='success',found=true
const calls=[],errors=[]
page.on('pageerror',e=>errors.push(e.message))
await context.addInitScript(()=>{localStorage.setItem('ark_access_token','synthetic-test-only');sessionStorage.setItem('leshine_welcome_shown_session','1')})
await context.route('**/api/**',async route=>{
  const req=route.request(),url=new URL(req.url()),path=url.pathname
  if(path==='/api/auth/me')return route.fulfill({json:{id:5,name:'Synthetic Admin',roles:[],permissions:['portal_site:admin']}})
  if(path==='/api/auth/refresh')return route.fulfill({json:{access_token:'synthetic-test-only'}})
  let data={}
  if(path.startsWith('/api/portal/admin/v1/catalog')){
    if(req.method()!=='GET'){
      const body=req.postDataJSON();calls.push({path,method:req.method(),body,version:req.headers()['if-match']})
      if(mode==='stale')return route.fulfill({status:409,json:{code:409,message:'标准规格已变化，请重新预览并核对单位换算。',data:{error_code:'SKU_CHANGED'}}})
      item={...item,...body,id,product_id:'101',sku_id:'201',product_kind:'hair',standard_json:standard,standard_fingerprint:fingerprint,row_version:(item?.row_version||0)+1,status:req.method()==='POST'?'draft':body.status,affected_customers:1,expired_quotes:2}
      if(mode==='lost')return route.abort('failed')
      data=item
    }else if(path.endsWith('/source'))data={source:{product_id:url.searchParams.get('product_id'),sku_id:url.searchParams.get('sku_id'),product_kind:'hair',standard_json:standard,standard_fingerprint:fingerprint},existing_item:item,expected_version:item?.row_version||0}
    else if(path.endsWith('/import-status'))data={found:found&&!!item,item:found?item:null}
    else if(path.endsWith('/'+id))data=item
    else data={items:item?[item]:[],total:item?1:0}
  }
  return route.fulfill({json:{code:200,message:'ok',data}})
})
const dialog=()=>page.locator('.portal-catalog-item:visible')
async function fillConfig(){
  for(const [name,value] of [['库存数量单位','g'],['销售单位','pack'],['每销售单位消耗的库存数量','20'],['库存安全余量','0']])await dialog().getByRole('textbox',{name,exact:true}).fill(value)
  await dialog().getByRole('spinbutton',{name:'起订量',exact:true}).fill('2')
  await dialog().getByRole('spinbutton',{name:'下单步长',exact:true}).fill('2')
  await dialog().getByRole('textbox',{name:'商品操作原因',exact:true}).fill('Reviewed real unit configuration')
}
async function confirm(){await dialog().locator('.el-checkbox').filter({hasText:'我已核对标准来源'}).click()}
try{
  await page.goto('http://127.0.0.1:3211/portal/catalog')
  await page.getByRole('button',{name:'导入标准 SKU',exact:true}).click()
  await dialog().getByRole('textbox',{name:'方舟产品 ID',exact:true}).fill('101');await dialog().getByRole('textbox',{name:'方舟 SKU ID',exact:true}).fill('201')
  await dialog().getByRole('button',{name:'预览标准来源',exact:true}).click()
  await dialog().getByRole('textbox',{name:'库存数量单位',exact:true}).waitFor()
  assert.equal(await dialog().getByRole('textbox',{name:'库存数量单位',exact:true}).inputValue(),'')
  await fillConfig();await confirm()
  await dialog().getByRole('textbox',{name:'方舟 SKU ID',exact:true}).fill('202')
  assert.equal(await dialog().getByRole('textbox',{name:'库存数量单位',exact:true}).count(),0)
  assert.equal(await dialog().getByRole('button',{name:'确认导入草稿',exact:true}).isDisabled(),true)
  await dialog().getByRole('textbox',{name:'方舟 SKU ID',exact:true}).fill('201');await dialog().getByRole('button',{name:'预览标准来源',exact:true}).click()
  await dialog().getByRole('textbox',{name:'库存数量单位',exact:true}).waitFor();await fillConfig();await confirm()
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000});assert.ok(await dialog().evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    await page.screenshot({animations:'disabled',path:`${process.env.PORTAL_QA_OUTPUT}/catalog-item-${width}.png`,fullPage:true})
  }
  mode='lost';await dialog().getByRole('button',{name:'确认导入草稿',exact:true}).click()
  await dialog().getByRole('button',{name:'查询原商品当前记录',exact:true}).waitFor()
  assert.equal(await dialog().getByRole('textbox',{name:'方舟产品 ID',exact:true}).isDisabled(),true)
  assert.equal(calls[0].version,'"0"');assert.equal(calls[0].body.standard_fingerprint,fingerprint);assert.equal('status' in calls[0].body,false)
  found=false;await dialog().getByRole('button',{name:'查询原商品当前记录',exact:true}).click()
  await dialog().getByText('尚未找到导入记录，不能据此判断原请求未执行。请稍后再次查询。',{exact:true}).waitFor()
  assert.equal(await dialog().getByRole('button',{name:'关闭',exact:true}).isDisabled(),true)
  found=true;await dialog().getByRole('button',{name:'查询原商品当前记录',exact:true}).click();await dialog().waitFor({state:'hidden'})
  await page.getByText('已查询到当前商品，不能据此确认原写入成功。请从列表重新打开核对；本次未重发写入。',{exact:true}).waitFor();assert.equal(calls.length,1)
  await page.getByRole('button',{name:'管理商品',exact:true}).click();await dialog().getByRole('textbox',{name:'库存数量单位',exact:true}).waitFor()
  assert.equal(await dialog().getByRole('textbox',{name:'方舟产品 ID',exact:true}).isDisabled(),true)
  await dialog().locator('.el-radio-button').filter({hasText:'已发布'}).click()
  await dialog().getByRole('textbox',{name:'商品操作原因',exact:true}).fill('Publish verified product');await confirm()
  mode='success';await dialog().getByRole('button',{name:'保存商品配置',exact:true}).click();await dialog().waitFor({state:'hidden'})
  assert.equal(calls[1].method,'PATCH');assert.equal(calls[1].version,'"1"');assert.equal(calls[1].body.status,'published');assert.equal('standard_fingerprint' in calls[1].body,false)
  await page.getByRole('button',{name:'管理商品',exact:true}).click();await dialog().getByRole('textbox',{name:'库存数量单位',exact:true}).waitFor()
  await dialog().getByRole('button',{name:'重新预览来源并准备导入草稿',exact:true}).click()
  await dialog().getByRole('button',{name:'确认导入草稿',exact:true}).waitFor()
  assert.equal(await dialog().getByRole('textbox',{name:'库存数量单位',exact:true}).inputValue(),'')
  await fillConfig();await confirm();mode='stale';await dialog().getByRole('button',{name:'确认导入草稿',exact:true}).click()
  await dialog().getByText('标准规格已变化，请重新预览并核对单位换算。',{exact:true}).waitFor()
  assert.equal(calls[2].version,'"2"');assert.equal(calls[2].method,'POST')
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({status:'pass',simulatedWrites:calls.length,scenarios:['no inferred units','source change invalidates preview','fingerprint-bound import version zero','unknown freezes and does not retry','missing readback remains unknown','found readback is not receipt','existing source locked','versioned publish','reimport clears conversion','stale source rejection','1440/390/320 layout']}))
}finally{await browser.close()}
