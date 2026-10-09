import fs from 'node:fs'
import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require=createRequire(import.meta.url)
const input=JSON.parse(fs.readFileSync(0,'utf8'))
const {chromium}=require(input.playwright)
const browser=await chromium.launch({headless:true,executablePath:input.chromium})
const cases=[]
async function control(path,method='GET') {
  const response=await fetch(input.origin+'/__test_control__/'+path,{method,headers:{'x-fixture-key':input.key}})
  assert.equal(response.status,200)
  return response.json()
}
async function until(fn) {const end=Date.now()+10000;while(Date.now()<end){const result=await fn();if(result)return result;await new Promise(resolve=>setTimeout(resolve,20))}throw new Error('Controlled wait timeout')}
for(const method of ['refresh','logout','login']) {
  const context=await browser.newContext({viewport:{width:1440,height:1000}}),page=await context.newPage()
  let gate
  try {
    await page.route('**/*',route=>new URL(route.request().url()).origin===input.origin?route.continue():route.abort())
    await page.goto(input.origin+'/login')
    await page.waitForFunction(()=>document.querySelector('#app').__vue_app__?.config.globalProperties.$pinia._s.has('auth'))
    await page.evaluate(()=>document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('auth').initPromise)
    async function login(identity) {
      await page.evaluate(async value=>{
        const app=document.querySelector('#app').__vue_app__,auth=app.config.globalProperties.$pinia._s.get('auth')
        await auth.login(value.username,value.password)
        await app.config.globalProperties.$router.push('/invoice/manage')
      },identity)
    }
    await login(input.A)
    await page.getByRole('heading',{name:'订单发票管理',level:2,exact:true}).waitFor()
    const cookieA=(await context.cookies()).find(cookie=>cookie.name==='refresh_token')
    assert.ok(cookieA);assert.equal(cookieA.httpOnly,true);assert.equal(cookieA.path,'/api/auth');assert.equal(cookieA.sameSite,'Lax')
    gate=(await control('arm/'+method,'POST')).id
    await page.evaluate(value=>{
      const auth=document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('auth')
      window.__heldAuthOutcome=null
      const pending=value.method==='refresh'?auth.refreshToken():value.method==='logout'?auth.logout():auth.login(value.identity.username,value.identity.password)
      pending.then(result=>window.__heldAuthOutcome={settled:true,result:value.method==='logout'?result:null},error=>window.__heldAuthOutcome={settled:true,code:error.code})
    },{method,identity:input.A})
    const ready=await until(async()=>{const status=await control('status/'+gate);return status.ready?status:null})
    assert.equal(ready.downstream_status,200)
    await login(input.B)
    const cookieB=(await context.cookies()).find(cookie=>cookie.name==='refresh_token')
    assert.ok(cookieB);assert.notEqual(cookieB.value,cookieA.value)
    // Release even a non-canceling baseline, so the old Set-Cookie really gets a chance to arrive.
    await control('release/'+gate,'POST')
    const finished=await until(async()=>{const status=await control('status/'+gate);return status.finished?status:null})
    await page.waitForFunction(()=>window.__heldAuthOutcome?.settled===true)
    const after=(await context.cookies()).find(cookie=>cookie.name==='refresh_token')
    assert.ok(after);assert.equal(after.value,cookieB.value)
    // Check current identity BEFORE a fresh refresh could repair an old A token using B's cookie.
    const beforeRefresh=await page.evaluate(async()=>{
      const auth=document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('auth')
      await auth.fetchMe();return {id:auth.user?.id,path:location.pathname}
    })
    assert.equal(beforeRefresh.id,input.B.id);assert.equal(beforeRefresh.path,'/invoice/manage')
    const outcome=await page.evaluate(()=>window.__heldAuthOutcome)
    if(method==='logout')assert.equal(outcome.result,false)
    else assert.equal(outcome.code,'ARK_AUTH_OPERATION_SUPERSEDED')
    assert.equal(finished.disconnected,true)
    const identity=await page.evaluate(async()=>{
      const auth=document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('auth')
      await auth.refreshToken();await auth.fetchMe()
      return {id:auth.user.id,username:auth.user.username,permissions:auth.user.permissions,path:location.pathname}
    })
    assert.equal(identity.id,input.B.id);assert.equal(identity.username,input.B.username);assert.ok(identity.permissions.includes('invoice:read'));assert.equal(identity.path,'/invoice/manage')
    // Force bootstrap to prove the browser's HttpOnly cookie still belongs to B.
    await page.evaluate(()=>localStorage.removeItem('ark_access_token'))
    await page.reload()
    await page.waitForFunction(()=>document.querySelector('#app').__vue_app__?.config.globalProperties.$pinia._s.has('auth'))
    await page.evaluate(()=>document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('auth').initPromise)
    const restored=await page.evaluate(()=>document.querySelector('#app').__vue_app__.config.globalProperties.$pinia._s.get('auth').user?.id)
    assert.equal(restored,input.B.id)
    cases.push({method,passed:true,real_http:true,real_cookie:true,old_transport_disconnected:true,after_auth_route_completed:true,after_committed_mutation:method!=='refresh',server_deleted_cookie_header:finished.cookie_delete_header,server_set_cookie_header:finished.cookie_set_header,reload_restored_B:true})
  } catch(error) {
    const frame=String(error?.stack||'').match(/authCookieRace\.browser\.mjs:(\d+):(\d+)/)
    cases.push({method,passed:false,error_type:error?.constructor?.name||'Unknown',driver_frame:frame?frame[1]+':'+frame[2]:null})
  } finally {
    if(gate)await control('release/'+gate,'POST').catch(()=>{})
    await context.close()
  }
}
await browser.close()
const result={scope:'compiled candidate / actual auth router service JWT / owned MySQL / loopback HTTP HttpOnly same-site cookies / controlled post-route response hold; login/logout mutations committed; refresh is read-only; not TLS, full main, cross-tab or distributed refresh certification',tests:cases.length,passed:cases.filter(value=>value.passed).length,failed:cases.filter(value=>!value.passed).length,cases}
fs.writeFileSync(process.argv[2],JSON.stringify(result)+'\n')
process.stdout.write('Owned finite browser result recorded\n')
process.exitCode=cases.some(value=>!value.passed)?1:0
