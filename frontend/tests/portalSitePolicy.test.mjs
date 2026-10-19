import test from 'node:test'
import assert from 'node:assert/strict'
import { sitePolicyPayload } from '../src/views/portal/sitePolicy.mjs'
const form = () => ({ name: ' LeShine ', reason: ' Approved ', status: 'enabled', quote_valid_minutes: 15, proposal_hours: '24, 48', payment_terms: [{ code: 'prepaid', display_text: 'Payment before shipment', deposit_percent: '100.00' }], default_payment_term_code: 'prepaid', origin: 'not writable', currency: 'EUR' })
test('payload whitelists policy and preserves decimal strings', () => {
  const result=sitePolicyPayload(form())
  assert.deepEqual(Object.keys(result).sort(), ['name','policy','reason','status'])
  assert.equal(result.name,'LeShine'); assert.equal(result.policy.payment_terms[0].deposit_percent,'100.00')
  assert.deepEqual(result.policy.proposal_valid_hours,[24,48])
})
test('enabled site requires explicit approved terms and default', () => {
  for (const change of [{payment_terms:[],default_payment_term_code:null},{default_payment_term_code:'missing'},{default_payment_term_code:null}]) assert.throws(()=>sitePolicyPayload({...form(),...change}))
  assert.equal(sitePolicyPayload({...form(),status:'disabled',payment_terms:[],default_payment_term_code:null}).policy.payment_terms.length,0)
})
test('invalid duplicate ranges and monetary percentages rejected', () => {
  for (const proposal_hours of ['24,24','0','169','1.5','24,','1,2,3,4,5,6,7,8,9']) assert.throws(()=>sitePolicyPayload({...form(),proposal_hours}))
  for (const deposit_percent of ['100.01','-1.00','1e2','100','01.00']) { const f=form();f.payment_terms[0].deposit_percent=deposit_percent;assert.throws(()=>sitePolicyPayload(f)) }
  const f=form();f.payment_terms.push({...f.payment_terms[0]});assert.throws(()=>sitePolicyPayload(f))
})

test('outward contacts are explicit whitelisted employee approvals', () => {
  const f=form(); f.sales_contacts=[{user_id:'7',display_name:' April ',email:'public@example.com',whatsapp:'',approved:true,private_phone:'never'}]
  const row=sitePolicyPayload(f).policy.sales_contacts[0]
  assert.deepEqual(row,{user_id:'7',display_name:'April',email:'public@example.com',whatsapp:null,approved:true})
  f.sales_contacts.push({...f.sales_contacts[0]}); assert.throws(()=>sitePolicyPayload(f))
})

test('auto fees carry payment surcharge per term and strictly increasing tiers', async () => {
  const { parseTiers, formatTiers } = await import('../src/views/portal/sitePolicy.mjs')
  const f = form()
  f.payment_terms = [{ code: 'bank', display_text: 'Bank transfer', deposit_percent: '100.00', method_label: ' Bank transfer ', surcharge_percent: '0.00' },
    { code: 'paypal', display_text: 'PayPal', deposit_percent: '100.00', method_label: 'PayPal', surcharge_percent: '5.00' }]
  f.default_payment_term_code = 'bank'
  f.auto_fees_enabled = true
  f.shipping_tiers = '300=40.00, 600=48.00，2000=96.00'
  const policy = sitePolicyPayload(f).policy
  assert.equal(policy.payment_terms[0].method_label, 'Bank transfer')
  assert.equal(policy.payment_terms[1].surcharge_percent, '5.00')
  assert.deepEqual(policy.auto_fees, { enabled: true, shipping_tiers: [{ max_grams: 300, fee: '40.00' }, { max_grams: 600, fee: '48.00' }, { max_grams: 2000, fee: '96.00' }] })
  assert.equal(formatTiers(policy.auto_fees.shipping_tiers), '300=40.00, 600=48.00, 2000=96.00')
  for (const tiers of ['600=48.00, 300=40.00', '300=40', '0=1.00', '', '300=40.00,300=41.00']) assert.throws(() => parseTiers(tiers))
  for (const surcharge_percent of ['100.00', '5', '-1.00']) { const g = structuredClone(f); g.payment_terms[1].surcharge_percent = surcharge_percent; assert.throws(() => sitePolicyPayload(g)) }
  assert.throws(() => sitePolicyPayload({ ...f, shipping_tiers: '' }))
  assert.deepEqual(sitePolicyPayload({ ...form() }).policy.auto_fees, { enabled: false })
})
