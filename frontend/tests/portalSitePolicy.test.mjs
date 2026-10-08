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
