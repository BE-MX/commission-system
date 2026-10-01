import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive, nextTick } from 'vue'
import { useCursorResource } from '../src/composables/useCursorResource.js'
import { viewController } from './helpers/viewController.mjs'
import * as workspace from '../src/views/customer_hub/customerWorkspaceController.js'
import * as workbench from '../src/views/customer_hub/workbenchV2Controller.js'
import * as runtime from '../src/views/agent-runtime/agentRuntimeView.js'
import * as money from '../src/utils/money.js'
const deferred = () => { let resolve; const promise = new Promise(yes => { resolve = yes }); return { promise, resolve } }

test('cursor append retries the same cursor, retains rows, deduplicates and rejects overlapping loads', async () => {
  const requests = []; let fail = false, slow
  const state = useCursorResource(async (scope, cursor) => {
    requests.push({ scope, cursor }); if (fail) throw Error('page offline'); if (slow) await slow.promise
    return cursor == null ? { items: [{ id: 1 }], nextCursor: 'page-2', hasMore: true } : { items: [{ id: 1 }, { id: 2 }], nextCursor: null, hasMore: false }
  })
  await state.load(7); fail = true; assert.equal(await state.load(7), false)
  assert.equal(state.isStale.value, true); assert.deepEqual(state.items.value, [{ id: 1 }])
  fail = false; slow = deferred(); const pending = state.load(7)
  assert.equal(await state.load(7), false); slow.resolve(); await pending
  assert.deepEqual(requests.map(request => request.cursor), [null, 'page-2', 'page-2'])
  assert.deepEqual(state.items.value.map(item => item.id), [1, 2]); assert.equal(state.hasMore.value, false)
})

test('cursor clear aborts old scope and allows a new scope before a late page settles', async () => {
  const old = deferred(); let signal
  const state = useCursorResource(async (scope, cursor, context) => {
    if (scope === 1) { signal = context.signal; await old.promise }
    return { items: [{ id: scope }], nextCursor: null, hasMore: false }
  })
  const pending = state.load(1); state.clear(); await state.load(2)
  assert.equal(signal.aborted, true); old.resolve(); assert.equal(await pending, false)
  assert.deepEqual(state.items.value, [{ id: 2 }])
})

test('workspace conversation and global pending pages fail independently; scope switches clear selected messages', async t => {
  const props = reactive({ customerId: 1 }); const old = deferred(), calls = []
  const { vm } = viewController(t, '../../src/views/customer_hub/workspace/WorkspaceConversations.vue', 'conversationState,pendingState,activeConversation,messageState,selectConversation', {
    '@props': props, '../customerWorkspaceController': workspace, '../workbenchV2Controller': workbench,
    '@/api/customerHub': {
      listCustomerConversations: async (id, params, config) => { calls.push({ id, params }); assert.equal(config.suppressToast, true); return { data: { items: [{ id }], total: 101 } } },
      listPendingBindings: async () => { throw Error('pending offline') },
      listConversationMessages: async () => old.promise,
    },
  })
  await nextTick(); await vm.conversationState.handleSizeChange(50); await vm.conversationState.handlePageChange(2)
  assert.deepEqual(calls.at(-1), { id: 1, params: { page: 2, page_size: 50 } })
  assert.equal(vm.pendingState.hasLoaded.value, false); assert.equal(vm.conversationState.hasLoaded.value, true)
  const selection = vm.selectConversation({ id: 10 }); props.customerId = 2; await nextTick()
  old.resolve({ data: { items: [{ id: 999 }], has_more: false } }); await selection
  assert.equal(vm.activeConversation.value, null); assert.deepEqual(vm.messageState.items.value, [])
  assert.equal(vm.conversationState.list.value[0].id, 2)
})

test('binding write keeps customer snapshot and preserves a newly opened customer dialog', async t => {
  const props = reactive({ customerId: 1 }), write = deferred(), writes = []
  const { vm, messages } = viewController(t, '../../src/views/customer_hub/workspace/WorkspaceConversations.vue', 'openBinding,bind,bindingEvidence,bindingVisible,selectedBinding', {
    '@props': props, '../customerWorkspaceController': workspace, '../workbenchV2Controller': workbench,
    '@/api/customerHub': {
      listCustomerConversations: async () => ({ data: { items: [], total: 0 } }), listPendingBindings: async () => { throw Error('pending offline') },
      createConversationBinding: async payload => { writes.push(payload); await write.promise },
    },
  })
  const row = { source_system: 'whatsapp', source_account_key: 'account', source_conversation_id: 'conversation', binding_version: 4 }
  vm.openBinding(row); vm.bindingEvidence.value = [{ evidence_type: 'manual_note', note: 'ownership checked' }]
  const saving = vm.bind(); await nextTick(); props.customerId = 2; vm.openBinding({ ...row, source_conversation_id: 'new' })
  write.resolve(); await saving
  assert.equal(writes[0].customer_id, 1); assert.equal(vm.bindingVisible.value, true)
  assert.equal(vm.selectedBinding.value.source_conversation_id, 'new'); assert.ok(messages.includes('会话已绑定'))
})

test('agent events advance after_sequence beyond 500 and retain the cursor when the next chunk fails', async t => {
  let fail = false; const calls = [], route = reactive({ params: { runId: 1 } })
  const { vm } = viewController(t, '../../src/views/agent-runtime/AgentRunDetail.vue', 'eventResource,events,loadEvents,stopPolling,runResource', {
    'vue-router': { useRoute: () => route, useRouter: () => ({ push() {} }) }, './agentRuntimeView': runtime, '../../utils/money.js': money,
    '@/api/agentRuntime': {
      getAgentRun: async () => ({ data: { run: { id: 1, status: 'completed' }, artifacts: [] } }),
      getAgentEvents: async (id, params, config) => {
        calls.push(params.after_sequence); assert.equal(config.suppressToast, true)
        if (fail) throw Error('events offline')
        return { data: params.after_sequence === 0 ? Array.from({ length: 500 }, (_, index) => ({ id: index + 1, sequence_no: index + 1 })) : [{ id: 501, sequence_no: 501 }] }
      },
    },
  })
  t.after(vm.stopPolling); await nextTick(); await new Promise(resolve => setImmediate(resolve))
  assert.equal(vm.eventResource.hasMore.value, true); fail = true; await vm.loadEvents()
  assert.equal(vm.events.value.length, 500); assert.equal(vm.eventResource.isStale.value, true)
  fail = false; await vm.loadEvents(); assert.deepEqual(calls, [0, 500, 500]); assert.equal(vm.events.value.length, 501)
  assert.equal(vm.eventResource.hasMore.value, false)
})

test('agent cancellation confirmation cannot write into another run after navigation', async t => {
  const confirmation = deferred(), route = reactive({ params: { runId: 1 } }), writes = []
  const { vm } = viewController(t, '../../src/views/agent-runtime/AgentRunDetail.vue', 'cancelRun,stopPolling,runResource', {
    'vue-router': { useRoute: () => route, useRouter: () => ({ push() {} }) }, './agentRuntimeView': runtime, '../../utils/money.js': money,
    '@/utils/feedback': { confirmAction: () => confirmation.promise },
    '@/api/agentRuntime': {
      getAgentRun: async id => ({ data: { run: { id, status: 'running' }, artifacts: [] } }), getAgentEvents: async () => ({ data: [] }),
      cancelAgentRun: async id => { writes.push(id) },
    },
  })
  t.after(vm.stopPolling); await new Promise(resolve => setImmediate(resolve))
  const cancelling = vm.cancelRun(); route.params.runId = 2; confirmation.resolve(); await cancelling
  assert.deepEqual(writes, [])
})
