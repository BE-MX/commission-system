import { createRequire } from 'node:module'
import assert from 'node:assert/strict'
const require=createRequire(import.meta.url)
const { chromium }=require(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const browser=await chromium.launch({executablePath:process.env.PORTAL_CHROMIUM,headless:true})
const context=await browser.newContext({viewport:{width:1440,height:1050}}), page=await context.newPage()
let value={configured:false,row_version:0,site_code:'leshine',origin:'https://portal.example',currency:'USD',language:'en',policy:{quote_valid_minutes:15,proposal_valid_hours:[24,48],payment_terms:[],default_payment_term_code:null}}, mode='success'
const calls=[],errors=[]
page.on('pageerror',e=>errors.push(e.message))
await context.addInitScript(()=>{localStorage.setItem('ark_access_token','synthetic-test-only');sessionStorage.setItem('leshine_welcome_shown_session','1')})
await context.route('**/api/**',async route=>{
  const req=route.request(),path=new URL(req.url()).pathname
  if(path==='/api/auth/me')return route.fulfill({json:{id:5,name:'Synthetic Admin',roles:[],permissions:['portal_site:admin']}})
  if(path==='/api/auth/refresh')return route.fulfill({json:{access_token:'synthetic-test-only'}})
  let data={}
  if(path==='/api/portal/admin/v1/settings'){
    if(req.method()==='PATCH'){
      calls.push({body:req.postDataJSON(),version:req.headers()['if-match']})
      if(mode==='stale')return route.fulfill({status:409,json:{code:409,message:'记录已变化，请刷新确认。',data:{error_code:'VERSION_CONFLICT'}}})
      value={...value,...req.postDataJSON(),configured:true,id:'11111111-1111-4111-8111-111111111111',row_version:value.row_version+1}
      if(mode==='lost')return route.abort('failed')
    }else if(mode==='denied')return route.fulfill({status:403,json:{code:403,message:'当前员工无此操作权限。',data:{error_code:'ACTION_FORBIDDEN'}}})
    data=value
  }
  return route.fulfill({json:{code:200,message:'ok',data}})
})
async function confirm(){await page.getByRole('textbox',{name:'站点操作原因'}).fill('Reviewed approved policy');await page.locator('.el-checkbox').filter({hasText:'我已核对启停'}).click()}
try{
  await page.goto('http://127.0.0.1:3211/portal/settings')
  await page.getByText('尚未初始化 · 版本 0',{exact:true}).waitFor()
  await page.getByRole('textbox',{name:'站点名称',exact:true}).fill('LeShine Test')
  await page.locator('.el-radio-button').filter({hasText:'启用'}).click();await confirm()
  await page.getByRole('button',{name:'保存站点配置',exact:true}).click()
  await page.getByText('启用前必须配置并确认付款条件。',{exact:true}).waitFor();assert.equal(calls.length,0)
  await page.locator('.el-radio-button').filter({hasText:'停用'}).click();await page.locator('.el-checkbox').filter({hasText:'我已核对启停'}).click()
  await page.getByRole('button',{name:'保存站点配置',exact:true}).click()
  await page.getByText('已配置 · 版本 1',{exact:true}).waitFor()
  assert.equal(calls[0].version,'"0"');assert.equal(calls[0].body.status,'disabled');assert.equal('origin' in calls[0].body,false)
  await page.getByRole('button',{name:'添加付款条件',exact:true}).click()
  await page.getByRole('textbox',{name:'付款代码 1',exact:true}).fill('prepaid')
  await page.getByRole('textbox',{name:'付款说明 1',exact:true}).fill('Payment before shipment')
  await page.getByRole('textbox',{name:'定金比例 1',exact:true}).fill('100.00')
  await page.locator('.default-term .el-select').click();await page.getByRole('option',{name:'prepaid · Payment before shipment',exact:true}).click()
  await page.locator('.el-radio-button').filter({hasText:'启用'}).click();await confirm()
  await page.getByRole('textbox',{name:'提案有效期',exact:true}).fill('24, 72')
  assert.equal(await page.getByRole('button',{name:'保存站点配置',exact:true}).isDisabled(),true)
  await page.locator('.el-checkbox').filter({hasText:'我已核对启停'}).click()
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:1000})
    assert.ok(await page.locator('.portal-settings').evaluate(el=>el.scrollWidth<=el.clientWidth+1))
    await page.screenshot({animations:'disabled',path:`${process.env.PORTAL_QA_OUTPUT}/site-settings-${width}.png`,fullPage:true})
  }
  mode='lost';await page.getByRole('button',{name:'保存站点配置',exact:true}).click()
  await page.getByText('保存结果未知，表单已冻结。请读取当前配置核对，不会自动重试保存。',{exact:true}).waitFor()
  assert.equal(await page.getByRole('textbox',{name:'站点名称',exact:true}).isDisabled(),true)
  assert.equal(calls[1].version,'"1"');assert.equal(calls[1].body.policy.payment_terms[0].deposit_percent,'100.00')
  mode='success';await page.getByRole('button',{name:'读取当前配置并放弃草稿',exact:true}).click()
  await page.getByText('已读取当前配置并放弃本地草稿；不能据此确认先前保存成功。本次未重发写入。',{exact:true}).waitFor()
  assert.equal(calls.length,2);await page.getByText('已配置 · 版本 2',{exact:true}).waitFor()
  mode='stale';await confirm();await page.getByRole('button',{name:'保存站点配置',exact:true}).click()
  await page.getByText('记录已变化，请刷新确认。',{exact:true}).waitFor();assert.equal(calls[2].version,'"2"')
  mode='denied';await page.getByRole('button',{name:'读取当前配置并放弃草稿',exact:true}).click()
  await page.getByText('当前员工无此操作权限。',{exact:true}).waitFor()
  assert.equal(await page.getByRole('textbox',{name:'站点名称',exact:true}).count(),0)
  assert.deepEqual(errors,[])
  console.log(JSON.stringify({status:'pass',simulatedWrites:calls.length,scenarios:['version zero initialize disabled','enable requires terms','payload whitelist','terms and default selection','edit invalidates confirmation','1440/390/320 layout','unknown freezes and no retry','readback is not receipt','stale version rejection','scope loss clears form']}))
}finally{await browser.close()}
