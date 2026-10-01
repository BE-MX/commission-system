import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { availableItemOperations, buildItemTransition, buildVersionedActionUpdate, createSubmissionIdentity, evidenceReference, normalizeWorkspaceTab, ITEM_VIEWS, errorMessage } from '../src/views/customer_hub/workbenchV2Controller.js'
import { createCustomerHubApi } from '../src/api/customerHubContract.js'
const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
const item = { can_operate: true, row_version: 7, allowed_operations: ['resolve','revalidate','reverify','reopen','pause','resume','wait','block','snooze'] }
const ref = { type: 'event', id: 81, revision: 2 }
test('three exclusive views preserve distinct work item and action count units', () => {
  assert.deepEqual(ITEM_VIEWS.map(row=>row.value), ['need_me','in_progress','ended'])
  const source=read('../src/views/customer_hub/WorkbenchList.vue')
  assert.match(source,/count_unit\s*!==\s*'work_item'/)
  assert.match(source,/actions_done_today/)
  assert.match(source,/items_resolved \+ summary.items_cancelled/)
  assert.match(source,/完成、终止和延后都不释放当日额度/)
})
test('only server permissions and allowed operations grant state transitions', () => {
  assert.deepEqual(availableItemOperations({...item,can_operate:false}),[])
  assert.throws(()=>buildItemTransition({...item,can_operate:false},'resume'),/不允许/)
  assert.throws(()=>buildItemTransition({...item,row_version:null},'resume'),/版本/)
  assert.throws(()=>buildItemTransition(item,'cancel',{reason:'x'}),/不允许/)
})
test('result confirmation and reopening require reason and versioned evidence', () => {
  for (const operation of ['resolve','revalidate','reopen']) {
    assert.throws(()=>buildItemTransition(item,operation,{reason:'已处理'}),/证据/)
    assert.throws(()=>buildItemTransition(item,operation,{reason:' ',evidence_refs:[ref]}),/原因/)
    assert.throws(()=>buildItemTransition(item,operation,{reason:'确认',evidence_refs:[{type:'event',id:81}]}),/版本/)
    assert.equal(buildItemTransition(item,operation,{reason:'客户已确认',evidence_refs:[ref]}).expected_item_version,7)
  }
  assert.equal(buildItemTransition(item,'resolve',{reason:'客户已确认',evidence_refs:[ref],cancel_remaining:true}).cancel_remaining,true)
  assert.equal(buildItemTransition(item,'resolve',{reason:'客户已确认',evidence_refs:[ref]}).cancel_remaining,undefined)
})
test('waiting and pause preserve explicit continuation conditions and review time', () => {
  assert.throws(()=>buildItemTransition(item,'pause',{reason:'暂无需求'}),/恢复条件/)
  assert.throws(()=>buildItemTransition(item,'wait',{reason:'已联系',review_at:'2026-10-01T09:00:00',waiting_kind:'customer'}),/条件/)
  assert.throws(()=>buildItemTransition(item,'block',{reason:'等待资料'}),/核验时间/)
  assert.equal(buildItemTransition(item,'wait',{reason:'已联系',review_at:'2026-10-01T09:00:00',waiting_kind:'customer',resume_condition:'客户确认需求'}).waiting_kind,'customer')
})
test('source reverification requires current versioned evidence and reason without claiming resolution', () => {
  assert.throws(()=>buildItemTransition(item,'reverify',{reason:'重新核验'}),/证据/)
  assert.throws(()=>buildItemTransition(item,'reverify',{reason:' ',evidence_refs:[ref]}),/原因/)
  const payload=buildItemTransition(item,'reverify',{reason:'来源已补齐',evidence_refs:[ref],cancel_remaining:true})
  assert.deepEqual(payload,{operation:'reverify',expected_item_version:7,reason:'来源已补齐',evidence_refs:[ref]})
  assert.throws(()=>buildItemTransition({...item,allowed_operations:['resume']},'reverify',{reason:'来源已补齐',evidence_refs:[ref]}),/不允许/)
})

test('delivery plan records a concrete decision, review time and real outbound source', () => {
  const delivery={...item,allowed_operations:['record_delivery_plan']}
  const form={reason:'已核实运单',delivery_decision:'alternative',delivery_plan:'分批发送',
    review_at:'2026-10-03T09:00:00',evidence_refs:[{type:'message',id:19,revision:'abc'}]}
  assert.deepEqual(buildItemTransition(delivery,'record_delivery_plan',form),{
    operation:'record_delivery_plan',expected_item_version:7,reason:'已核实运单',
    delivery_decision:'alternative',delivery_plan:'分批发送',review_at:'2026-10-03T09:00:00',
    evidence_refs:form.evidence_refs})
  assert.throws(()=>buildItemTransition(delivery,'record_delivery_plan',{...form,evidence_refs:[]}),/证据/)
  assert.throws(()=>buildItemTransition(delivery,'record_delivery_plan',{...form,delivery_plan:''}),/交付方案/)
  const detail=read('../src/views/customer_hub/WorkItemDetail.vue')
  assert.match(detail,/operation === 'record_delivery_plan'/)
  assert.match(detail,/evidenceKind.value = value === 'record_delivery_plan' \? 'message'/)
  const resolve={...item,goal_type:'delivery_exception'}
  assert.throws(()=>buildItemTransition(resolve,'resolve',{reason:'客户已回复',evidence_refs:form.evidence_refs}),/客户是否接受/)
  assert.throws(()=>buildItemTransition(resolve,'resolve',{reason:'客户已回复',evidence_refs:form.evidence_refs,customer_decision:'declined'}),/不能登记解决/)
  assert.equal(buildItemTransition(resolve,'resolve',{reason:'客户已接受',evidence_refs:form.evidence_refs,customer_decision:'accepted'}).customer_decision,'accepted')
})
test('PCW actions cannot bypass item action or occurrence version checks', () => {
  const action={work_item_id:4,row_version:2,work_item_version:7,occurrence_id:9,occurrence_version:3}
  const complete={operation:'complete',next_step:'核验客户是否回复',next_step_due_at:'2026-10-01T09:00:00'}
  const payload=buildVersionedActionUpdate(action,complete)
  assert.deepEqual(payload,{...complete,expected_action_version:2,expected_work_item_version:7,expected_occurrence_version:3})
  assert.throws(()=>buildVersionedActionUpdate({...action,occurrence_version:null},complete),/实例版本/)
  assert.throws(()=>buildVersionedActionUpdate({...action,work_item_version:null},complete),/事项版本/)
  assert.throws(()=>buildVersionedActionUpdate(action,{operation:'complete'}),/下一次/)
  assert.deepEqual(buildVersionedActionUpdate({}, {operation:'complete'}),{operation:'complete'})
})
test('sample commands use actual HTTP schema and real evidence references', async () => {
  const {buildSampleCasePayload}=await import('../src/views/customer_hub/customerWorkspaceController.js')
  const start=buildSampleCasePayload('start_test',{actual_date:'2026-09-30',evidence_refs:[ref]},{expected_sample_version:3})
  assert.deepEqual(start,{operation:'start_test',expected_sample_version:3,actual_date:'2026-09-30',evidence_refs:[ref]})
  const feedback=buildSampleCasePayload('record_feedback',{feedback:'客户反馈测试通过',feedback_date:'2026-09-30'},{expected_sample_version:4})
  assert.equal(feedback.feedback_text,'客户反馈测试通过');assert.equal(feedback.actual_date,'2026-09-30')
  assert.equal(feedback.feedback_date,undefined);assert.equal(start.evidence_message_ids,undefined)
  const panel=read('../src/views/customer_hub/workspace/WorkspaceMaintenance.vue')
  const conversations=read('../src/views/customer_hub/workspace/WorkspaceConversations.vue')
  assert.doesNotMatch(panel,/\[0\]|toISOString/)
  assert.doesNotMatch(conversations,/manual_verification/)
})
test('retry keeps identity and input changes including refreshed versions rotate identity', () => {
  let n=0;const identity=createSubmissionIdentity('test',()=>`key-${++n}`)
  assert.equal(identity.forPayload({expected_item_version:7,reason:'客户确认'}),'key-1')
  assert.equal(identity.forPayload({expected_item_version:7,reason:'客户确认'}),'key-1')
  assert.equal(identity.forPayload({expected_item_version:8,reason:'客户确认'}),'key-2')
  identity.reset();assert.equal(identity.forPayload({expected_item_version:8,reason:'客户确认'}),'key-3')
  assert.match(errorMessage({response:{status:409}}),/输入已保留/)
})
test('only live selectable versioned references are offered for result evidence', () => {
  assert.deepEqual(evidenceReference({id:81,selectable:true,evidence_ref:ref}),ref)
  assert.equal(evidenceReference({id:81,selectable:false,evidence_ref:ref}),null)
  assert.equal(evidenceReference({id:81,selectable:true}),null)
})
test('legacy deep links resolve inside the four shared tabs', () => {
  assert.equal(normalizeWorkspaceTab('orders'),'overview')
  assert.equal(normalizeWorkspaceTab('monitor'),'profile')
  assert.equal(normalizeWorkspaceTab('relationships'),'conversations')
  assert.equal(normalizeWorkspaceTab('unknown'),'overview')
  assert.match(read('../src/views/customer_hub/CustomerWorkbench.vue'),/initial-item-id/)
})
test('v2 endpoints preserve server payloads and idempotency headers', () => {
  const calls=[],client={get:(...args)=>calls.push(['get',...args]),post:(...args)=>calls.push(['post',...args])},api=createCustomerHubApi(client)
  const params={view:'ended',ended_state:'cancelled',customer_scope:'collaborator',action_scope:'visible',page:2,page_size:20}
  api.listWorkbenchItems(params);api.getWorkItem(4)
  const payload={operation:'pause',expected_item_version:7,reason:'暂无需求',resume_condition:'需求确认'}
  api.transitionWorkItem(4,payload,'pause-key')
  assert.deepEqual(calls,[['get','/workbench/items',{params,showLoading:false}],['get','/work-items/4',{showLoading:false}],['post','/work-items/4/transitions',payload,{headers:{'Idempotency-Key':'pause-key'}}]])
})
test('capacity admission is explicit and feedback remains dimensioned', () => {
  const list=read('../src/views/customer_hub/WorkbenchList.vue'),detail=read('../src/views/customer_hub/WorkItemDetail.vue')
  assert.match(list,/expected_plan_version:capacity.value.version/)
  assert.match(list,/allow_one_extra:allowExtra.value/)
  assert.match(list,/row.can_admit/)
  assert.match(detail,/scope:'prepare'/)
  assert.match(detail,/target_revision:feedbackTarget.value.target_revision/)
  assert.match(detail,/等待真实停止回执/)
  assert.match(detail,/delegation.outcome_uncertain/)
  assert.match(detail,/查询原运行回执/)
  assert.match(detail,/actual|实际采纳|采纳/)
  assert.doesNotMatch(detail,/模拟|mock|系统已发送/)
})
