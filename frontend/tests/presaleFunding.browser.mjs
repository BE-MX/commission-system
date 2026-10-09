import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
const require = createRequire(import.meta.url), {chromium} = require(process.argv[2]), {expect} = require(process.argv[2]+'/test.js')
const base = process.argv[3]
const browser = await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true})
const results = []
try {
  for (const width of [1440,390]) {
    const context = await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'})
    const page = await context.newPage(), errors = [], requests = []
    let summaryReads = 0, purpose = 'presale_deposit', version = 1
    const paid = () => ({id:1062,invoice_id:1,receipt_no:'TEST-PAID',source:'auto',purpose,version,status:'active',
      sync_status:'synced',collect_status:1,xiaoman_receipt_id:'7001',currency:'USD',amount:'1077',bank_charge:'0',
      collection_date:'2026-10-08',payment_type:'Other',remark:'',attachments:[]})
    page.on('pageerror', e => errors.push(e.message))
    await page.route(base+'/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      const respond = data => route.fulfill({json:{code:200,message:'ok',data}})
      if (path === '/api/receipts/invoice-summary/1') {
        summaryReads++
        return respond({initial_receipt:paid(),balance:{funding_mode:'presale_pool',pool_available_amount:'1077',
          pending_amount:'0',pool_balances:[{receipt_id:1062,purpose,effective:true,remaining_amount:'1077'}]}})
      }
      if (path === '/api/receipts/1062/presale-purpose') {
        const body = request.postDataJSON(); requests.push(body)
        assert.equal(body.version,version); assert.equal(body.purpose,'presale_advance')
        purpose = body.purpose; version++
        return respond(paid())
      }
      throw new Error('Unexpected API '+path)
    })
    await page.goto(base+'/tests/presaleFundingHarness.html')
    await page.getByRole('button',{name:'更正预售收款用途'}).click()
    const dialog = page.getByRole('dialog')
    await dialog.locator('.el-select').click()
    await page.getByRole('option',{name:'预付货款',exact:true}).click()
    await dialog.getByPlaceholder('填写客户付款用途的核对依据（至少10字）').fill('客户已确认这笔款为预付货款，从本批开始扣减')
    await dialog.getByRole('button',{name:'保存更正'}).click()
    try {
      await page.waitForFunction(() => window.testForm.receipt_draft.purpose === 'presale_advance'
        && window.testForm.receipt_draft.receipt_version === 2, null, {timeout:10000})
    } catch (e) {
      console.log(JSON.stringify({summaryReads,requests,errors,form:await page.evaluate(() => window.testForm),text:await page.locator('body').innerText()}))
      throw e
    }
    await page.getByRole('button',{name:'更正预售收款用途'}).click()
    await dialog.waitFor({state:'visible'})
    assert.match(await dialog.locator('.el-select').innerText(), /预付货款/)
    assert.equal(summaryReads,2); assert.equal(requests.length,1)
    assert.equal(await page.getByText('请核实退款安排',{exact:false}).count(),0)
    assert.deepEqual(errors,[])
    results.push({width,summaryReads,version,purpose})
    await context.close()
    const shippingContext = await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'})
    const shipping = await shippingContext.newPage(), quotes = [], submissions = [], shippingErrors = []
    shipping.on('pageerror', e => shippingErrors.push(e.message))
    await shipping.route(base+'/api/**', async route => {
      const request = route.request(), path = new URL(request.url()).pathname
      const respond = data => route.fulfill({json:{code:200,message:'ok',data}})
      if (path === '/api/invoice/invoices/1') return respond({id:1,invoice_no:'TEST-SHIP',currency:'USD',
        items:[{id:7,product_name:'Product A',quantity:4}]})
      if (path === '/api/shipments/order/1') return respond({items:[]})
      if (path === '/api/invoices/1/shipment-quotes') {
        const body = request.postDataJSON(); quotes.push(body)
        return respond({quote_hash:'a'.repeat(64),funding_version:2,is_final:body.is_final,goods_amount:'627',
          packaging_amount:'0',handling_amount:'0',freight_amount:'38',advance_applied:'665',deposit_applied:'0',
          new_payment_due:'0',pool_balances:[
            {purpose:'presale_advance',effective:true,remaining_amount:'412'},
            {purpose:'presale_deposit',effective:true,remaining_amount:'100'},
            {purpose:'presale_advance',effective:false,remaining_amount:'500'}]})
      }
      if (path === '/api/invoices/1/shipment-settlements') {
        const body = request.postDataJSON(); submissions.push(body)
        return respond({id:8,invoice_id:1,request_key:body.request_key,quote_hash:body.quote_hash,
          settlement_no:'TEST-01',version:1,state:'ready',quote:{}})
      }
      throw new Error('Unexpected shipping API '+path)
    })
    await shipping.goto(base+'/tests/shipmentSubmissionHarness.html')
    await shipping.getByRole('button',{name:'打开出库结算',exact:true}).click()
    const preview = shipping.getByRole('button',{name:'核算本批金额',exact:true})
    const submit = shipping.getByRole('button',{name:'生成本批结算单',exact:true})
    await preview.click()
    await shipping.getByText('请填写本批出库数量',{exact:true}).waitFor()
    assert.equal(quotes.length,0)
    await shipping.locator('.el-table').first().getByRole('spinbutton').fill('2')
    await shipping.keyboard.press('Tab')
    await expect(shipping.getByText('请填写本批出库数量',{exact:true})).toHaveCount(0)
    await preview.click(); await expect(submit).toBeEnabled()
    assert.equal(quotes[0].is_final,false)
    await shipping.locator('label.el-checkbox').filter({hasText:'人工确认：这是最后一批发货，可抵扣定金'}).click()
    await expect(submit).toBeDisabled()
    await preview.click(); await expect(submit).toBeEnabled()
    assert.equal(quotes[1].is_final,true)
    const summary = shipping.locator('.el-descriptions').filter({hasText:'扣减后可用预付货款'})
    await expect(summary).toContainText('412.00')
    await expect(summary).toContainText('留存定金（仅末批）')
    await expect(summary).toContainText('待生效款（不可用）')
    await submit.click(); await expect(shipping.getByRole('dialog')).toHaveCount(0)
    assert.equal(submissions[0].is_final,true)
    assert.deepEqual(submissions[0].items,[{invoice_item_id:7,quantity:2}])
    assert.deepEqual(shippingErrors,[])
    results.push({width,manualFinal:true,quantityErrorCleared:true,balancesSeparated:true})
    await shippingContext.close()
  }
  console.log(JSON.stringify({passed:true,results}))
} finally { await browser.close() }
