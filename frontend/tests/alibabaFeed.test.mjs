import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs/promises'
import vm from 'node:vm'
import * as vue from 'vue'
import { useListPage } from '../src/composables/useListPage.js'
import { analysisSelection, createReadScope, createRequestTask, minuteTime, directionText, canReadRecord, visibilityLabel } from '../src/views/alibaba_feed/feedState.js'

const row = (id, company = '9223372036854775800', eligible = true) => ({ id, mapping_version: 1, ai_eligible: eligible, link: company ? { id: id + 10, company_id: company, version: 1 } : null })
test('only explicitly selected, eligible snapshots linked to the same current customer may be analyzed', () => {
  for (const rows of [[], [row(1, null)], [row(1), row(2, 'other')], [row(1), row(2, undefined, false)], Array.from({ length: 26 }, (_, i) => row(i + 1))]) assert.equal(analysisSelection(rows).valid, false)
  assert.deepEqual(analysisSelection([row(7), row(8)]), { valid: true, companyId: '9223372036854775800', itemIds: [7, 8] })
})
test('a link revocation or changed eligibility immediately invalidates selected rows', () => {
  const rows = [row(1)]
  assert.equal(analysisSelection(rows).valid, true)
  rows[0].link = null
  assert.equal(analysisSelection(rows).valid, false)
})
test('a write task retains the exact request ID on uncertain outcome and refuses a different task', () => {
  let ids = 0
  const task = createRequestTask(() => `request-${++ids}`)
  assert.equal(task.begin('link', { item_id: 7, company_id: '99' }), 'request-1')
  task.uncertain()
  assert.equal(task.begin('link', { item_id: 7, company_id: '99' }), 'request-1')
  assert.throws(() => task.begin('link', { item_id: 7, company_id: '100' }), /待核对/)
  task.complete()
  assert.equal(task.begin('link', { item_id: 7, company_id: '100' }), 'request-2')
})
test('switching, closing or revoking authority prevents late private detail responses', () => {
  const scope = createReadScope(), first = scope.begin(), second = scope.begin()
  assert.equal(first.signal.aborted, true)
  assert.equal(first.isCurrent(), false)
  assert.equal(second.isCurrent(), true)
  scope.clear()
  assert.equal(second.isCurrent(), false)
})
test('external time is Beijing minute precision and directions are declared rather than guessed', () => {
  assert.equal(minuteTime('2026-11-04T16:00:39Z'), '2026-11-05 00:00')
  assert.equal(minuteTime('2026-11-05T00:00:39'), '2026-11-05 00:00')
  assert.equal(directionText('bot'), '平台机器人')
  assert.equal(directionText('unexpected'), '方向未提供')
})
test('phone layout keeps full buyer identity and actions together, and repeats identity in matching dialog', async () => {
  const page = await fs.readFile(new URL('../src/views/alibaba_feed/AlibabaFeed.vue', import.meta.url), 'utf8')
  const { parse } = await import('@vue/compiler-dom')
  const template = parse(page.slice(page.indexOf('<template>') + 10, page.indexOf('\n</template>')))
  const nodes = []
  function visit(node) { if (node.tag) nodes.push(node); for (const child of node.children || []) visit(child) }
  visit(template)
  const prop = (node, name) => node.props?.find(p => p.name === name)
  const binding = (node, name) => node.props?.find(p => p.name === 'bind' && p.arg?.content === name)?.exp?.content
  const buyer = nodes.find(node => node.tag === 'el-table-column' && prop(node, 'label')?.value?.content === '买家')
  assert.equal(binding(buyer, 'fixed'), "narrow ? false : 'left'")
  assert.equal(binding(buyer, 'show-overflow-tooltip'), '!narrow')
  assert.equal(buyer.props.find(p => p.name === 'if').exp.content, "narrow || visibleKeys.includes('buyer')")
  assert.ok(buyer.children.some(slot => slot.children?.some(child => child.tag === 'template' && child.children?.some(n => n.tag === 'FeedRecordActions'))))
  const actions = nodes.find(node => node.tag === 'el-table-column' && prop(node, 'label')?.value?.content === '操作')
  assert.equal(actions.props.find(p => p.name === 'if').exp.content, '!narrow')
  assert.match(page, /matchMedia\('\(max-width: 768px\)'\)/)
  assert.match(page, /@media \(max-width: 768px\)\s*\{\s*\.buyer-name, \.buyer-inquiry[^}]*white-space: normal;[^}]*overflow-wrap: anywhere/s)
  const identity = nodes.find(node => prop(node, 'class')?.value?.content === 'link-record-identity')
  assert.match(identity.loc.source, /linkRow\.buyer\?\.name/)
  assert.match(identity.loc.source, /linkRow\.inquiry_id/)
})

function deferred() { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b }); return { promise, resolve, reject } }
const settle = () => new Promise(resolve => setImmediate(resolve))
async function harness(overrides = {}) {
  const auth = vue.reactive({ user: { id: 1 }, permissions: ['client_desk:read', 'client_desk:write'], roles: [], hasPermission(value) { return this.permissions.includes(value) } })
  const calls = [], feedback = []
  const api = { records: async () => ({ items: [row(1)], total: 1 }), customers: async () => ({ items: [{ company_id: '99', name: 'Fixture' }], total: 1 }), record: async id => ({ id }), link: async data => { calls.push(data); return {} }, unlink: async () => ({}), ...overrides }
  const context = vm.createContext({ AbortController, crypto: globalThis.crypto })
  const modules = {
    vue,
    '@/api/alibabaFeed': { alibabaFeedApi: api }, '@/api/clientDesk': { clientDeskApi: { reanalyze: async (...args) => calls.push(args) } },
    '@/stores/auth': { useAuthStore: () => auth }, '@/composables/useListPage': { useListPage },
    '@/utils/errors': { errorMessage: error => error.message || 'failure' },
    '@/utils/feedback': { confirmAction: async () => {}, isFeedbackCancelled: () => false, msgSuccessText: text => feedback.push(text) },
    './feedState': { analysisSelection, createReadScope, createRequestTask, canReadRecord, visibilityLabel },
  }
  const code = await fs.readFile(new URL('../src/views/alibaba_feed/useAlibabaFeed.js', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(code, { context })
  await module.link(specifier => {
    const values = modules[specifier]
    if (!values) throw new Error(`Unexpected dependency ${specifier}`)
    return new vm.SyntheticModule(Object.keys(values), function () { for (const [key, value] of Object.entries(values)) this.setExport(key, value) }, { context })
  })
  await module.evaluate()
  const scope = vue.effectScope()
  const state = scope.run(() => module.namespace.useAlibabaFeed(vue.computed(() => auth.hasPermission('client_desk:read'))))
  await settle()
  return { state, auth, calls, feedback, stop: () => scope.stop() }
}
test('permission loss clears list, body and customer candidates and rejects late private reads', async () => {
  const detail = deferred(), customers = deferred()
  const h = await harness({ record: () => detail.promise, customers: () => customers.promise })
  const opening = h.state.openDetail(row(1))
  h.state.openLink(row(1))
  h.auth.permissions = []
  detail.resolve({ id: 1, messages: [{ text: 'private body' }] })
  customers.resolve({ items: [{ company_id: '99', name: 'private customer' }], total: 1 })
  await opening; await settle()
  assert.equal(h.state.detail.value, null)
  assert.equal(h.state.detailVisible.value, false)
  assert.equal(h.state.listPage.list.value.length, 0)
  assert.equal(h.state.customers.value.length, 0)
  h.stop()
})
test('503 remains a disabled error and cannot be presented as a successful empty result', async () => {
  const h = await harness({ records: async () => { throw { response: { status: 503 }, message: 'disabled' } } })
  assert.equal(h.state.listError.value, 'TM 资料试点尚未启用')
  assert.equal(h.state.listPage.isEmpty.value, false)
  h.stop()
})
test('revoked or remapped placeholders never request body and remain available for explicit reconfirmation', async () => {
  let reads = 0
  const h = await harness({ record: async () => { reads += 1; return { messages: ['private body'] } } })
  for (const [state, label] of [['link_revoked', '已撤销，需重新关联'], ['mapping_changed', '负责人映射已更新，需重新确认']]) {
    const placeholder = { ...row(4, null, false), visibility_state: state, buyer: { name: '资料待重新确认' } }
    assert.equal(canReadRecord(placeholder), false)
    assert.equal(visibilityLabel(placeholder), label)
    assert.equal(analysisSelection([{ ...row(4), visibility_state: state }]).valid, false)
    await h.state.openDetail(placeholder)
    assert.equal(h.state.detail.value, null)
    assert.equal(h.state.detailVisible.value, false)
    assert.equal(h.state.actionError.value, label)
    h.state.openLink(placeholder); await settle()
    assert.equal(h.state.linkVisible.value, true)
    assert.equal(h.state.linkRow.value.id, 4)
    assert.equal(h.state.customers.value.length, 1)
  }
  assert.equal(reads, 0)
  h.stop()
})
test('unknown link result sends once, preserves task state and blocks click retries', async () => {
  let sends = 0
  const h = await harness({ link: async () => { sends += 1; throw new Error('timeout') } })
  h.state.openLink(row(1)); await settle(); h.state.companyId.value = '99'
  await h.state.linkCustomer()
  assert.equal(h.state.uncertain.value, true)
  await h.state.linkCustomer()
  assert.equal(sends, 1)
  assert.match(h.state.actionError.value, /未自动重试/)
  h.stop()
})
