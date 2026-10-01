import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { birthdayFormFromContact, buildSourcedPlanPayload, shippingFormFromEvent } from '../src/views/customer_hub/maintenancePlanController.js'
import { createCustomerHubApi } from '../src/api/customerHubContract.js'
const fact={type:'fact',id:4,revision:'birthday-r1'}
const contact={contact_id:2,name:'Amy',birthday_month:2,birthday_day:29,birthday_evidence_refs:[fact],selectable:true}
const links=[{id:6,shipment_id:14,order_id:20,state:'active',selectable:true,link_version:3},{id:7,shipment_id:15,order_id:21,state:'active',selectable:true}]
const event={shipment_event_id:9,shipment_id:14,trigger_event_type:'delivered',source_revision:'delivery-r1',shipment_order_link_ids:[6],evidence_refs:[{type:'event',id:9,revision:'delivery-r1'}],selectable:true}
const sources={contacts:[contact],shipment_links:links,shipment_events:[event]}
test('birthday auto fills only confirmed contact facts and asks for leap policy',()=>{
  const form={title:'生日联系',...birthdayFormFromContact(contact)}
  assert.equal(form.leap_day_policy,'')
  assert.throws(()=>buildSourcedPlanPayload('birthday',form,sources),/闰日策略/)
  const payload=buildSourcedPlanPayload('birthday',{...form,leap_day_policy:'feb28'},sources)
  assert.equal(payload.typed_payload.contact_id,2);assert.equal(payload.typed_payload.leap_day_policy,'feb28')
  assert.deepEqual(payload.evidence_refs,[fact])
  assert.throws(()=>buildSourcedPlanPayload('birthday',{...form,leap_day_policy:'skip',evidence_refs:[{type:'fact',id:80,revision:'not-birthday'}]},sources),/生日事实/)
  assert.throws(()=>buildSourcedPlanPayload('birthday',{...form,leap_day_policy:'skip',month:4,day:31},sources),/有效的生日/)
  assert.throws(()=>buildSourcedPlanPayload('birthday',{...form,leap_day_policy:'skip',day:28},sources),/来源不一致/)
  assert.throws(()=>buildSourcedPlanPayload('birthday',{...form,leap_day_policy:'skip'},{contacts:[{...contact,selectable:false}]}),/已失效/)
})
test('ordinary birthdays still carry schema required leap policy',()=>{
  const ordinary={...contact,birthday_month:3,birthday_day:10}
  const payload=buildSourcedPlanPayload('birthday',{title:'生日联系',...birthdayFormFromContact(ordinary)},{contacts:[ordinary]})
  assert.equal(payload.typed_payload.leap_day_policy,'skip')
})
test('campaign keeps real version and verified audience in exact typed schema',()=>{
  const campaigns=[{id:12,status:'active',campaign_version:5}]
  const preview={campaign_id:12,campaign_version:5,preview_version:'audience-r5',eligible:[{customer_id:20}],expires_at:'2026-10-01T10:00:00+08:00'}
  const options={customerId:20,campaigns,campaignPreview:preview,now:Date.parse('2026-10-01T09:00:00+08:00')}
  const payload=buildSourcedPlanPayload('campaign',{title:'活动沟通',campaign_id:12},sources,options)
  assert.deepEqual(payload.typed_payload,{campaign_id:12,campaign_version:5,audience_decision_ref:'audience-r5'})
  assert.equal(payload.typed_payload.preview_version,undefined)
  assert.throws(()=>buildSourcedPlanPayload('campaign',{title:'活动沟通',campaign_id:12},sources,{...options,customerId:21}),/受众/)
  assert.throws(()=>buildSourcedPlanPayload('campaign',{title:'活动沟通',campaign_id:12},sources,{...options,now:Date.parse('2026-10-01T10:00:01+08:00')}),/过期/)
  assert.throws(()=>buildSourcedPlanPayload('campaign',{title:'活动沟通',campaign_id:12},sources,{...options,campaigns:[{...campaigns[0],campaign_version:6}]}),/重新预览/)
  assert.throws(()=>buildSourcedPlanPayload('campaign',{title:'活动沟通',campaign_id:12},sources,{...options,campaigns:[{...campaigns[0],status:'paused'}]}),/生效/)
})
test('shipping selects a real event and only its active exact order links',()=>{
  const form={title:'签收后沟通',contact_channel:'whatsapp',...shippingFormFromEvent(event)}
  const payload=buildSourcedPlanPayload('shipping',form,sources)
  assert.deepEqual(payload.typed_payload,{shipment_order_link_ids:[6],trigger_event_type:'delivered',shipment_event_id:9,contact_channel:'whatsapp'})
  assert.deepEqual(payload.evidence_refs,event.evidence_refs)
  assert.throws(()=>buildSourcedPlanPayload('shipping',{...form,shipment_order_link_ids:[7]},sources),/不匹配/)
  assert.throws(()=>buildSourcedPlanPayload('shipping',form,{...sources,shipment_links:[{...links[0],state:'revoked'}]}),/已撤销/)
  assert.throws(()=>buildSourcedPlanPayload('shipping',form,{...sources,shipment_events:[{...event,selectable:false}]}),/已失效/)
  assert.throws(()=>buildSourcedPlanPayload('shipping',{...form,shipment_order_link_ids:[]},sources),/已确认订单/)
})
test('all six types are offered and source ids have no hand entered substitutes',()=>{
  const editor=readFileSync(new URL('../src/views/customer_hub/workspace/MaintenancePlanEditor.vue',import.meta.url),'utf8')
  assert.match(editor,/v-for="type in MAINTENANCE_PLAN_TYPES"/)
  for(const type of ['manual','birthday','holiday','campaign','shipping','sample'])assert.match(editor,new RegExp(`planType==='${type}'`))
  assert.match(editor,/getMaintenancePlanSources/);assert.match(editor,/previewCampaign/)
  assert.doesNotMatch(editor,/shipment_event_id.*el-input|contact_id.*el-input|audience_decision_ref.*el-input/)
})
test('source read uses registered customer client and current customer',()=>{
  const calls=[],api=createCustomerHubApi({get:(...args)=>calls.push(args)})
  api.getMaintenancePlanSources(20)
  assert.deepEqual(calls,[['/customers/20/maintenance-plan-sources',{showLoading:false}]])
})
