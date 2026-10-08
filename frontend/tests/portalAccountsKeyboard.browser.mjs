import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { mkdir, writeFile } from 'node:fs/promises'
const { chromium } = createRequire(import.meta.url)(process.env.PORTAL_PLAYWRIGHT_MODULE || 'playwright')
const origin = process.env.PORTAL_PREVIEW_ORIGIN || 'http://127.0.0.1:3211', output = process.env.PORTAL_QA_OUTPUT, motion = process.env.PORTAL_UI_MOTION || 'reduce'
assert.match(origin, /^http:\/\/127\.0\.0\.1:\d+$/); assert.ok(output); assert.ok(['reduce', 'no-preference'].includes(motion)); await mkdir(output, { recursive: true })
const widths = process.env.PORTAL_UI_WIDTHS ? process.env.PORTAL_UI_WIDTHS.split(',').map(Number) : [1440,390,320]
assert.ok(widths.length && widths.every(width=>[1440,390,320].includes(width)))
const browser = await chromium.launch({ executablePath: process.env.PORTAL_CHROMIUM, headless: true }), results = []
const accessId = '11111111-1111-4111-8111-111111111111', accountId = '22222222-2222-4222-8222-222222222222', invitationId = '33333333-3333-4333-8333-333333333333'
function gate() { let release; const waiting = new Promise(resolve => { release = resolve }); return { waiting, release } }
async function reach(page, target) { await target.waitFor({ state: 'attached' }); for (let i=0; i<180; i++) { if (await target.evaluate(el => el === document.activeElement)) return; await page.keyboard.press('Tab') }; throw new Error('Unreachable '+await target.evaluate(el => el.outerHTML)) }
async function activate(page, target, key='Enter') { await reach(page, target); await page.keyboard.press(key) }
async function type(page, target, value) { await reach(page, target); await page.keyboard.press('Control+A'); await page.keyboard.press('Backspace'); await page.keyboard.type(value); await page.keyboard.press('Tab') }
async function focused(page, target) { await target.waitFor({ state: 'visible' }); await page.waitForFunction(el => el === document.activeElement, await target.elementHandle()); assert.equal(await target.evaluate(el => el === document.activeElement), true) }
async function geometry(page, dialog) {
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false, 'No root overflow')
  assert.deepEqual(await dialog.evaluate(el => { const r=el.getBoundingClientRect(), bad=[]; if (r.left < -1 || r.right > innerWidth+1 || r.top < -1 || r.bottom > innerHeight+1 || el.scrollWidth > el.clientWidth+1) bad.push('dialog bounds'); for (const field of el.querySelectorAll('input,textarea,.el-dialog__footer button')) { const b=field.getBoundingClientRect(); if (!b.width || !b.height) continue; if (b.left < r.left-1 || b.right > r.right+1) bad.push(field.getAttribute('aria-label') || field.textContent); if (field.closest('.el-dialog__footer') && (b.top < r.top-1 || b.bottom > r.bottom+1)) bad.push('footer'); }; return bad }), [])
}
try {
  for (const width of widths) {
    const context = await browser.newContext({ viewport: { width, height: 950 }, reducedMotion: motion })
    await context.addInitScript(() => { localStorage.setItem('ark_access_token','synthetic-account-keyboard'); sessionStorage.setItem('leshine_welcome_shown_session','1') })
    const page=await context.newPage(), errors=[], writes=[], blocked=[], invitationEffects=new Map(); let writeGate, readGate, refreshGate, mode='ready', readMode='ready', scopeDenied=false, permissions=['portal_access:read','portal_access:admin']
    const company='KeyboardBuyerCompany'.repeat(6).slice(0,100), existingEmail='existing@keyboard.example.test', email='a'.repeat(64)+'@'+'b'.repeat(63)+'.'+'c'.repeat(63)+'.'+'d'.repeat(56)+'.test', contact='ApprovedBuyerContact'.repeat(6).slice(0,100), reason='ReviewedAccountPolicy'.repeat(25).slice(0,500)
    assert.equal(email.length,254)
    let access={ id:accessId, company_display_name:company, status:'enabled', row_version:3, canonical_customer_id:'9007199254740993', sales_user_id:'5', capabilities:{can_view_price:true,can_order:true}, catalog_version:1, mapping_version:1, catalog_item_ids:['existing-product'] }
    let account={ id:accountId, email:existingEmail, contact_name:'Existing Buyer', status:'active', row_version:3, email_verified:true, membership_status:'active', invitation:{id:invitationId,status:'pending',row_version:1} }
    page.on('pageerror',e=>errors.push(e.message))
    await context.route('**/*',route=>{const url=new URL(route.request().url());if(url.origin===origin)return route.continue();blocked.push(url.href);return route.abort()})
    await context.route('**/api/**',async route=>{
      const req=route.request(), path=new URL(req.url()).pathname, send=(data,status=200,message='OK')=>route.fulfill({status,json:{code:status,message,data}})
      if(path==='/api/auth/me')return route.fulfill({json:{id:5,name:'Synthetic employee',roles:[],permissions}})
      if(path==='/api/auth/refresh')return route.fulfill({json:{access_token:'synthetic-account-keyboard'}})
      if(!path.startsWith('/api/portal/admin/v1/'))return send({})
      if(req.method()==='GET') {
        await refreshGate?.waiting
        if(path.endsWith('/customers'))return scopeDenied ? send({error_code:'ACTION_FORBIDDEN'},403,'当前员工无此操作权限。') : send({items:[access],total:1})
        if(path.endsWith('/customers/'+accessId)) {
          const selectedReadMode=readMode; await readGate?.waiting
          if(selectedReadMode==='fail')return send({error_code:'SERVICE_UNAVAILABLE'},503,'当前状态暂不可用，请重试。')
          if(selectedReadMode==='denied'||scopeDenied){scopeDenied=true;return send({error_code:'RESOURCE_NOT_FOUND'},404,'记录不存在或不在当前授权范围内。')}
          return send({...access,accounts:{items:[account],total:1,page:1,page_size:20}})
        }
        throw new Error('Unexpected read '+path)
      }
      const selectedMode=mode, operation={path,method:req.method(),body:req.postDataJSON(),version:req.headers()['if-match'],key:req.headers()['idempotency-key']};writes.push(operation);await writeGate?.waiting
      if(selectedMode==='denied'){scopeDenied=true;return send({error_code:'ACTION_FORBIDDEN'},403,'当前员工无此操作权限。')}
      if(selectedMode==='stale')return send({error_code:'VERSION_CONFLICT'},409,'记录已变化，请刷新确认。')
      if(path.endsWith('/customers/'+accessId+'/invitations')) {
        assert.deepEqual(operation.body,{email,contact_name:contact});assert.match(operation.key,/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i)
        if(!invitationEffects.has(operation.key)){invitationEffects.set(operation.key,operation.body);account={...account,email,contact_name:contact,status:'invited',email_verified:false,invitation:{id:invitationId,status:'pending',row_version:1}}}
        else assert.deepEqual(invitationEffects.get(operation.key),operation.body)
        if(selectedMode==='lost')return route.abort('failed')
        return send({invitation_id:invitationId,event_id:'44444444-4444-4444-8444-444444444444',row_version:1,replayed:true})
      }
      assert.equal(operation.body.reason,reason)
      if(path.endsWith('/accounts/'+accountId)) {assert.equal(operation.version,'"'+account.row_version+'"');account={...account,status:operation.body.status,row_version:account.row_version+1};if(selectedMode==='lost')return route.abort('failed');return send(account)}
      if(path.endsWith('/customers/'+accessId)) {assert.equal(operation.version,'"'+access.row_version+'"');assert.deepEqual(operation.body,{status:'suspended',capabilities:{can_view_price:false,can_order:false},reason});access={...access,...operation.body,row_version:access.row_version+1};return send(access)}
      if(path.endsWith('/invitations/'+invitationId+'/revoke')) {assert.equal(operation.version,'"1"');account.invitation={...account.invitation,status:'revoked',row_version:2};return send({id:invitationId,row_version:2,revoked:true})}
      throw new Error('Unexpected write '+path)
    })
    const drawer=page.getByRole('dialog',{name:'客户访问与账号',exact:true}), action=page.locator('.portal-access-action:visible')
    const confirm=()=>action.getByRole('checkbox',{name:'我已核对客户与影响，确认本次操作',exact:true}), submit=()=>action.getByRole('button',{name:'确认操作',exact:true})
    async function openDetail(){await activate(page,page.getByRole('button',{name:'管理',exact:true}));await drawer.waitFor();await drawer.getByRole('heading',{name:company,exact:true}).waitFor()}
    async function sendAction(nextMode,retry=false){mode=nextMode;writeGate=gate();await activate(page,action.getByRole('button',{name:retry?'重试原邀请':'确认操作',exact:true}));await action.getByRole('status').filter({hasText:'正在提交账号操作，请等待回执…'}).waitFor();assert.equal(await action.locator('.access-action-content').getAttribute('aria-busy'),'true');writeGate.release()}
    async function inspect(nextMode){readMode=nextMode;readGate=gate();await activate(page,action.getByRole('button',{name:'读取当前状态',exact:true}));await action.getByRole('status').filter({hasText:'正在读取当前客户与账号状态…'}).waitFor();readGate.release()}
    async function hiddenPrivate(){await page.waitForFunction(values=>values.every(value=>!document.body.innerText.includes(value)),[company,existingEmail,email,contact]);assert.equal(await action.getByRole('textbox',{name:'采购邮箱',exact:true}).count(),0);assert.equal(await action.getByRole('textbox',{name:'采购联系人',exact:true}).count(),0)}
    try {
      await page.goto(origin+'/portal/customers');await openDetail();await activate(page,drawer.getByRole('button',{name:'邀请采购账号',exact:true}))
      await activate(page,confirm(),'Space');await activate(page,submit());const invalid=action.getByRole('alert').filter({hasText:'请填写有效邮箱和采购联系人。'});await focused(page,invalid);await activate(page,submit());await focused(page,invalid);assert.equal(writes.length,0)
      await type(page,action.getByRole('textbox',{name:'采购邮箱',exact:true}),email);await type(page,action.getByRole('textbox',{name:'采购联系人',exact:true}),contact);await activate(page,confirm(),'Space')
      await reach(page,action.getByRole('textbox',{name:'采购联系人',exact:true}));await page.keyboard.press('ArrowLeft');await page.keyboard.press('ArrowRight');await page.keyboard.press('Tab');assert.equal(await confirm().isChecked(),true)
      await type(page,action.getByRole('textbox',{name:'采购联系人',exact:true}),contact.slice(0,-1));assert.equal(await confirm().isChecked(),false);assert.equal(await submit().isDisabled(),true);await type(page,action.getByRole('textbox',{name:'采购联系人',exact:true}),contact);await activate(page,confirm(),'Space');await geometry(page,action);await page.screenshot({path:output+'/invite-'+width+'.png',fullPage:true})
      await sendAction('lost');const network=action.getByRole('alert').filter({hasText:'网络连接中断，请按页面提示核对。'});await focused(page,network);assert.equal(await action.getByRole('textbox',{name:'采购邮箱',exact:true}).isDisabled(),true);assert.equal(await action.getByRole('button',{name:'读取当前状态',exact:true}).count(),0);await page.keyboard.press('Escape');assert.equal(await action.count(),1)
      const dialogPromise=page.waitForEvent('dialog'), reload=page.reload({timeout:5000}).then(()=>false,()=>true);const dialog=await dialogPromise;assert.equal(dialog.type(),'beforeunload');await dialog.dismiss();assert.equal(await reload,true);assert.equal(writes.length,1);assert.equal(await action.getByRole('textbox',{name:'采购邮箱',exact:true}).isDisabled(),true)
      await sendAction('denied',true);const denied=action.getByRole('alert').filter({hasText:'当前员工无此操作权限。'});await focused(page,denied);await hiddenPrivate();assert.equal(await action.getByRole('button',{name:'取消',exact:true}).isDisabled(),true);assert.equal(await action.getByRole('button',{name:'重试原邀请',exact:true}).isVisible(),true);await geometry(page,action)
      scopeDenied=false;await sendAction('ready',true);await action.waitFor({state:'hidden'});await focused(page,page.getByRole('button',{name:'管理',exact:true}));assert.deepEqual(writes.slice(0,3).map(x=>({body:x.body,key:x.key})),Array(3).fill({body:{email,contact_name:contact},key:writes[0].key}));assert.equal(invitationEffects.size,1)
      await openDetail();await activate(page,drawer.getByRole('button',{name:'停用账号',exact:true}));await type(page,action.getByRole('textbox',{name:'操作原因',exact:true}),reason);await activate(page,confirm(),'Space');await sendAction('lost');await focused(page,network);assert.equal(await action.getByRole('button',{name:'重试原邀请',exact:true}).count(),0)
      await inspect('fail');await focused(page,action.getByRole('alert').filter({hasText:'当前状态暂不可用，请重试。'}));assert.equal(await action.getByRole('textbox',{name:'操作原因',exact:true}).isDisabled(),true)
      await inspect('denied');await focused(page,action.getByRole('alert').filter({hasText:'记录不存在或不在当前授权范围内。'}));await hiddenPrivate();assert.equal(await action.getByRole('button',{name:'读取当前状态',exact:true}).isVisible(),true)
      scopeDenied=false;await inspect('ready');await action.waitFor({state:'hidden'});await focused(page,page.getByRole('button',{name:'管理',exact:true}));assert.equal(writes.filter(x=>x.path.endsWith('/accounts/'+accountId)).length,1,'Unknown account edit was never resent')
      await openDetail();await activate(page,drawer.getByRole('button',{name:'恢复账号',exact:true}));await action.getByRole('alert').filter({hasText:'此邮箱尚未验证。恢复为待邀请后'}).waitFor();await activate(page,confirm(),'Space');await activate(page,submit());const reasonError=action.getByRole('alert').filter({hasText:'请填写 1–500 字的操作原因。'});await focused(page,reasonError);await activate(page,submit());await focused(page,reasonError)
      await type(page,action.getByRole('textbox',{name:'操作原因',exact:true}),reason);await activate(page,confirm(),'Space');await sendAction('stale');await focused(page,action.getByRole('alert').filter({hasText:'记录已变化，请刷新确认。'}));assert.equal(await action.getByRole('textbox',{name:'操作原因',exact:true}).inputValue(),reason);await sendAction('ready');await action.waitFor({state:'hidden'});await focused(page,drawer.getByRole('button',{name:'停用账号',exact:true}));assert.equal(account.status,'invited','Unverified account restores only to invited')
      await activate(page,drawer.getByRole('button',{name:'撤销邀请',exact:true}));await type(page,action.getByRole('textbox',{name:'操作原因',exact:true}),reason);await activate(page,confirm(),'Space');await sendAction('ready');await action.waitFor({state:'hidden'});await focused(page,drawer.getByRole('button',{name:'邀请采购账号',exact:true}));await drawer.getByText('最近邀请：已撤销',{exact:true}).waitFor()
      await activate(page,drawer.getByRole('button',{name:'设置客户访问',exact:true}));await reach(page,action.getByRole('radio',{name:'启用',exact:true}));await page.keyboard.press('ArrowRight');assert.equal(await action.getByRole('radio',{name:'暂停',exact:true}).isChecked(),true);await activate(page,action.getByRole('checkbox',{name:'允许查看价格、订单金额与 PI',exact:true}),'Space');assert.equal(await action.getByRole('checkbox',{name:'允许下单及确认交易条件',exact:true}).isChecked(),false)
      await type(page,action.getByRole('textbox',{name:'操作原因',exact:true}),reason);await activate(page,confirm(),'Space');await geometry(page,action);await page.screenshot({path:output+'/access-'+width+'.png',fullPage:true});await sendAction('ready');await action.waitFor({state:'hidden'});await focused(page,drawer.getByRole('button',{name:'设置客户访问',exact:true}));assert.equal(await drawer.getByRole('button',{name:'邀请采购账号',exact:true}).isDisabled(),true);assert.deepEqual(access.catalog_item_ids,['existing-product'])
      // The user can leave the parent drawer while a successful action's refresh is still pending.
      await activate(page,drawer.getByRole('button',{name:'设置客户访问',exact:true}));await type(page,action.getByRole('textbox',{name:'操作原因',exact:true}),reason);await activate(page,confirm(),'Space');refreshGate=gate();await sendAction('ready');await action.waitFor({state:'hidden'});await page.keyboard.press('Escape');await drawer.waitFor({state:'hidden'});const search=page.getByRole('textbox',{name:'搜索客户',exact:true});await reach(page,search);await page.keyboard.type('NewSearchIntent');refreshGate.release();await page.getByRole('button',{name:'管理',exact:true}).waitFor();await page.waitForFunction(()=>!document.querySelector('.portal-customers .el-loading-mask'));await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));assert.equal(await search.evaluate(el=>el===document.activeElement),true,'A late action refresh must not steal focus after the user leaves its parent drawer');assert.equal(await search.inputValue(),'NewSearchIntent');await openDetail()
      await activate(page,drawer.getByRole('button',{name:'停用账号',exact:true}));await type(page,action.getByRole('textbox',{name:'操作原因',exact:true}),reason);await activate(page,confirm(),'Space');await sendAction('denied');await focused(page,denied);await hiddenPrivate();assert.equal(await submit().count(),0);assert.equal(await action.getByRole('button',{name:'取消',exact:true}).isDisabled(),false);await activate(page,action.getByRole('button',{name:'取消',exact:true}));await action.waitFor({state:'hidden'});await focused(page,page.getByRole('button',{name:'刷新',exact:true}))
      scopeDenied=false;mode='ready';permissions=['portal_access:read'];await page.reload();await openDetail();assert.equal(await drawer.getByRole('button',{name:'设置客户访问',exact:true}).isVisible(),false);assert.equal(await drawer.getByRole('button',{name:'停用账号',exact:true}).isVisible(),false)
      assert.equal(writes.length,10);assert.deepEqual(errors,[]);assert.ok(blocked.some(url=>new URL(url).hostname==='fonts.googleapis.com'))
      results.push({width,motion,keyboard:true,unknownBeforeUnload:true,lateRefreshDoesNotStealFocus:true,simulatedWriteAttempts:writes.length,simulatedInvitationEffects:invitationEffects.size,pageErrors:errors.length,lengths:{company:company.length,email:email.length,contact:contact.length,reason:reason.length}})
    } catch(error) {await page.screenshot({path:output+'/failure-'+width+'.png',fullPage:true});await writeFile(output+'/failure-'+width+'.json',JSON.stringify(await page.evaluate(()=>({active:document.activeElement?.outerHTML?.slice(0,900),text:document.body.innerText.slice(-16000)})),null,2));throw error}
    finally {writeGate?.release();readGate?.release();refreshGate?.release();await context.close()}
  }
  const result={status:'pass',scope:'Built employee UI; intercepted synthetic identity/account/access/invitation APIs. No real backend, RBAC, persistence or SMTP proof.',results};await writeFile(output+'/result.json',JSON.stringify(result,null,2));console.log(JSON.stringify(result))
} finally {await browser.close()}