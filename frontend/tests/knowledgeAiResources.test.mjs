import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import * as Vue from 'vue'
import { useAsyncResource } from '../src/composables/useAsyncResource.js'
import { loadComponent, mountComponent, slotShell } from './helpers/mountComponent.mjs'

const deferred = () => { let resolve, reject; const promise = new Promise((r, j) => { resolve = r; reject = j }); return { promise, resolve, reject } }
const flush = async () => { await Promise.resolve(); await Vue.nextTick(); await Promise.resolve(); await Promise.resolve() }
const settingsPath = '../src/views/knowledge/KnowledgeAiSettings.vue'
const drawerPath = '../src/views/knowledge/components/AiOptimizationDrawer.vue'
const defaultApi = () => ({ listAiProfiles: async () => ({ data: [] }), listAiPresetCandidates: async () => ({ data: [] }), listAiLibraryCandidates: async () => ({ data: [] }), listAiProfileLogs: async () => ({ data: [] }), listDocumentAiJobs: async () => ({ data: [] }) })
function controller(t, path, api = {}, props = {}) {
  let source = readFileSync(new URL(path, import.meta.url), 'utf8').match(/<script setup>([\s\S]*?)<\/script>/)[1]
  source = source.replace(/^import\s+([\s\S]*?)\s+from\s+['"]([^'"]+)['"];?/gm, (_, binding, key) => `const ${binding.trim().startsWith('{') ? binding.replace(/\bas\b/g, ':') : `{default:${binding}}`} = modules[${JSON.stringify(key)}] || {};`)
  const auth = Vue.reactive({ user: { id: 1 }, roles: [], permissions: [] }), notices = [], timers = new Map()
  const modules = { vue: { ...Vue, onMounted() {}, onBeforeUnmount() {} }, '@/composables/useAsyncResource': { useAsyncResource }, '@/stores/auth': { useAuthStore: () => auth }, '@/api/knowledge': { ...defaultApi(), ...api }, '@/utils/feedback': { confirmAction: async () => {}, msgError() {}, msgSuccess: message => notices.push(message) }, '@/utils/datetime': {}, '@/composables/useTableView': { useTableView: () => ({}) } }
  const scope = Vue.effectScope(); t.after(() => scope.stop())
  const result = path === settingsPath ? '{load,profiles,presets,libraries,profilesResource,presetsResource,librariesResource,logsResource,logs,logsProfile,logsDrawer,openLogs,loadLogs,save,remove,form,dialog,clearScope}' : '{loadProfiles,restoreLatestJob,openDrawer,clearScope,profilesResource,historyResource,jobResource,profiles,profileId,job,start,poll,cancel,apply,reset,starting,applying}'
  const state = scope.run(() => new Function('modules', 'defineProps', 'defineEmits', 'window', `${source}\nreturn ${result}`)(modules, () => props, () => (...args) => notices.push(args), { setTimeout: fn => { const id = timers.size + 1; timers.set(id, fn); return id }, clearTimeout: id => timers.delete(id) }))
  return { state, auth, notices, timers }
}

test('settings collections fail independently and preserve successful arrays on later read failure', async t => {
  let fail = false
  const { state } = controller(t, settingsPath, { listAiProfiles: async () => { if (fail) throw new Error('profile offline'); return { data: [{ id: 1 }] } }, listAiPresetCandidates: async () => { throw new Error('preset offline') }, listAiLibraryCandidates: async () => ({ data: [{ id: 3 }] }) })
  await state.load(); assert.equal(state.profiles.value[0].id, 1); assert.equal(state.libraries.value[0].id, 3); assert.equal(state.presetsResource.errorMessage.value, 'preset offline'); fail = true; await state.profilesResource.load(); assert.equal(state.profiles.value[0].id, 1); assert.equal(state.profilesResource.isStale.value, true)
})

test('settings log drawer opens before first error; profile switch and close reject late prior logs', async t => {
  const queue = []; const { state } = controller(t, settingsPath, { listAiProfileLogs: (id, config) => { const p = deferred(); queue.push({ ...p, id, config }); return p.promise } })
  const old = state.openLogs({ id: 1 }); assert.equal(state.logsDrawer.value, true); const current = state.openLogs({ id: 2 }); assert.equal(queue[0].config.signal.aborted, true); queue[1].reject(new Error('logs offline')); await current; assert.equal(state.logsResource.errorMessage.value, 'logs offline'); queue[0].resolve({ data: [{ id: 11 }] }); await old; assert.deepEqual(state.logs.value, [])
  const retry = state.loadLogs(); assert.equal(queue[2].id, 2); queue[2].resolve({ data: [{ id: 22 }] }); await retry; const late = state.loadLogs(); state.logsDrawer.value = false; await flush(); assert.equal(queue[3].config.signal.aborted, true); queue[3].resolve({ data: [{ id: 99 }] }); await late; assert.deepEqual(state.logs.value, [])
})

test('optimization library/document switch clears resources and late history cannot restore prior document job', async t => {
  const profiles = [], history = [], props = Vue.reactive({ modelValue: true, document: { id: 1, library_id: 1, revision_id: 10 }, dirty: false })
  const { state } = controller(t, drawerPath, { listAiProfiles: (id, config) => { const p = deferred(); profiles.push({ ...p, id, config }); return p.promise }, listDocumentAiJobs: (id, config) => { const p = deferred(); history.push({ ...p, id, config }); return p.promise } }, props)
  const old = state.openDrawer(); props.document = { id: 2, library_id: 2, revision_id: 20 }; await flush(); assert.equal(history[0].config.signal.aborted, true); assert.equal(profiles[0].config.signal.aborted, true)
  profiles[1].resolve({ data: [{ id: 22 }] }); history[1].resolve({ data: [{ id: 222, document_id: 2, status: 'completed' }] }); await flush(); profiles[0].resolve({ data: [{ id: 11 }] }); history[0].resolve({ data: [{ id: 111, document_id: 1, status: 'completed' }] }); await old; assert.equal(state.job.value.id, 222); assert.equal(state.profileId.value, 22)
})


test('settings successful save/delete resolve separately from three independent failed rereads', async t => {
  const writes = []
  const { state, notices } = controller(t, settingsPath, { createAiProfile: async payload => { writes.push(payload); return { data: { id: 9 } } }, deleteAiProfile: async id => { writes.push(id) }, listAiProfiles: async () => { throw new Error('profiles reread') }, listAiPresetCandidates: async () => { throw new Error('presets reread') }, listAiLibraryCandidates: async () => { throw new Error('libraries reread') } })
  Object.assign(state.form, { name: 'Fixture', preset_id: 7, source_library_ids: [1], target_library_ids: [2] }); state.dialog.value = true; await state.save(); assert.equal(state.dialog.value, false); assert.deepEqual(notices, ['保存']); assert.equal(writes[0].require_citations, true); assert.deepEqual(writes[0].source_library_ids, [1]); assert.equal(state.profilesResource.errorMessage.value, 'profiles reread'); assert.equal(state.presetsResource.errorMessage.value, 'presets reread'); assert.equal(state.librariesResource.errorMessage.value, 'libraries reread'); await state.remove({ id: 9, name: 'Fixture' }); assert.equal(writes[1], 9); assert.deepEqual(notices, ['保存', '删除'])
})

test('settings forced actor switch aborts all reads and rejects a successful late config write refresh', async t => {
  const reads = [], write = deferred(); const { state, auth, notices } = controller(t, settingsPath, { listAiProfiles: (_, config) => { const p = deferred(); reads.push({ ...p, config }); return p.promise }, createAiProfile: () => write.promise })
  const old = state.load(); Object.assign(state.form, { name: 'Private', preset_id: 7, source_library_ids: [1], target_library_ids: [2] }); const saving = state.save(); auth.user = { id: 2 }; await flush(); assert.equal(reads[0].config.signal.aborted, true); assert.deepEqual(state.profiles.value, []); write.resolve({ data: { id: 9 } }); await saving; assert.deepEqual(notices, []); assert.equal(reads.length, 2); reads[1].resolve({ data: [{ id: 2 }] }); await flush(); reads[0].resolve({ data: [{ id: 1 }] }); await old; assert.equal(state.profiles.value[0].id, 2)
})

test('optimization historical read failure blocks duplicate creation and retry preserves submitted document', async t => {
  let failed = true, creates = 0; const ids = [], props = Vue.reactive({ modelValue: true, document: { id: 7, library_id: 3, revision_id: 70 }, dirty: false })
  const { state } = controller(t, drawerPath, { listAiProfiles: async id => ({ data: [{ id: 4, library_id: id }] }), listDocumentAiJobs: async (id, config) => { ids.push({ id, config }); if (failed) throw new Error('history offline'); return { data: [] } }, createDocumentAiJob: async () => { creates++; return { data: { id: 77, status: 'queued' } } } }, props)
  await state.openDrawer(); assert.equal(state.historyResource.errorMessage.value, 'history offline'); await state.start(); assert.equal(creates, 0); failed = false; await state.restoreLatestJob(); assert.equal(ids[1].id, 7); assert.ok(ids[1].config.signal instanceof AbortSignal); await state.start(); assert.equal(creates, 1); assert.equal(state.job.value.id, 77)
})

test('optimization scope close aborts pending restore/profile/poll and late create cannot populate reopened document', async t => {
  const created = deferred(), polled = deferred(), props = Vue.reactive({ modelValue: true, document: { id: 1, library_id: 1, revision_id: 10 }, dirty: false })
  let pollConfig
  const { state } = controller(t, drawerPath, { listAiProfiles: async () => ({ data: [{ id: 4 }] }), listDocumentAiJobs: async () => ({ data: [] }), createDocumentAiJob: () => created.promise, getDocumentAiJob: (_, config) => { pollConfig = config; return polled.promise } }, props)
  await state.openDrawer(); const creation = state.start(); props.modelValue = false; await flush(); props.document = { id: 2, library_id: 2, revision_id: 20 }; props.modelValue = true; await flush(); created.resolve({ data: { id: 11, document_id: 1, status: 'queued' } }); await creation; assert.equal(state.job.value, null)
  state.job.value = { id: 22, document_id: 2, status: 'running' }; const read = state.poll(); props.modelValue = false; await flush(); assert.equal(pollConfig.signal.aborted, true); polled.resolve({ data: { id: 22, status: 'completed' } }); await read; assert.equal(state.job.value, null)
})

test('optimization poll failures preserve successful job, retry same ID and canceled job rejects earlier poll', async t => {
  const queue = [], props = Vue.reactive({ modelValue: true, document: { id: 1, library_id: 1 }, dirty: false })
  const { state } = controller(t, drawerPath, { listDocumentAiJobs: async () => ({ data: [{ id: 11, status: 'running' }] }), getDocumentAiJob: (id, config) => { const p = deferred(); queue.push({ ...p, id, config }); return p.promise }, cancelDocumentAiJob: async () => ({ data: { id: 11, status: 'cancelled' } }) }, props)
  await state.openDrawer(); const first = state.poll(); queue[0].reject(new Error('poll offline')); await first; assert.equal(state.job.value.status, 'running'); assert.equal(state.jobResource.errorMessage.value, 'poll offline'); const retry = state.poll(); assert.equal(queue[1].id, 11); queue[1].resolve({ data: { id: 11, status: 'running' } }); await retry; const old = state.poll(); await state.cancel(); assert.equal(queue[2].config.signal.aborted, true); queue[2].resolve({ data: { id: 11, status: 'completed' } }); await old; assert.equal(state.job.value.status, 'cancelled')
})

test('optimization cancel failure resumes polling and apply success retains original result event', async t => {
  const props = Vue.reactive({ modelValue: true, document: { id: 1, library_id: 1 }, dirty: false })
  const { state, timers, notices } = controller(t, drawerPath, { listDocumentAiJobs: async () => ({ data: [{ id: 11, status: 'running' }] }), cancelDocumentAiJob: async () => { throw new Error('cancel write failed') }, applyDocumentAiJob: async id => ({ data: { document_id: 1, job_id: id } }) }, props)
  await state.openDrawer(); await assert.rejects(state.cancel(), /cancel write failed/); assert.equal(timers.size, 1); state.job.value.status = 'completed'; await state.apply(); assert.equal(state.job.value.status, 'applied'); assert.equal(timers.size, 0); assert.deepEqual(notices, ['AI 优化结果已应用为新草稿', ['applied', { document_id: 1, job_id: 11 }]])
})

test('knowledge AI read API optional configs forward AbortSignal, preserve full/bounded params and silent defaults', async () => {
  const calls = [], client = { get: (path, config) => { calls.push({ path, config }); return {} } }
  const source = readFileSync(new URL('../src/api/knowledge.js', import.meta.url), 'utf8').replace(/^import .*$/m, '').replace(/export /g, '')
  const api = new Function('knowledgeClient', `${source}; return {listAiProfiles,listAiPresetCandidates,listAiLibraryCandidates,listAiProfileLogs,listDocumentAiJobs,getDocumentAiJob}`)(client)
  const signal = new AbortController().signal, config = { signal, suppressToast: true }; api.listAiProfiles(3, config); api.listAiPresetCandidates(config); api.listAiLibraryCandidates(config); api.listAiProfileLogs(7, config); api.listDocumentAiJobs(9, config); api.getDocumentAiJob(11, config)
  assert.equal(calls.length, 6); for (const call of calls) { assert.equal(call.config.signal, signal); assert.equal(call.config.suppressToast, true); assert.equal(call.config.showLoading, false) }; assert.deepEqual(calls[0].config.params, { target_library_id: 3 }); assert.equal(calls[3].path, '/ai-profiles/7/logs'); assert.equal(calls[4].path, '/documents/9/ai-jobs'); api.listAiProfiles(); assert.deepEqual(calls[6].config, { params: {}, showLoading: false })
})


const button = { inheritAttrs: false, emits: ['click'], setup: (_, { attrs, slots, emit }) => () => Vue.h('button', { ...attrs, onClick: () => emit('click') }, slots.default?.()) }
const visibleShell = { props: ['modelValue'], setup: (props, { slots }) => () => props.modelValue ? Vue.h('section', slots.default?.()) : null }
const status = loadComponent('../../src/components/ListPageStatus.vue', { '@element-plus/icons-vue': { Refresh: {} }, './GlassButton.vue': { default: button } })
function mountedModules(api) {
  return { vue: { ...Vue, resolveDirective: () => ({}) }, '@/api/knowledge': { ...defaultApi(), ...api }, '@/composables/useAsyncResource': { useAsyncResource }, '@/stores/auth': { useAuthStore: () => ({ user: { id: 1 }, roles: [], permissions: [] }) }, '@/utils/feedback': { msgError() {}, msgSuccess() {}, confirmAction: async () => {} }, '@/utils/datetime': { formatBeijingDateTime: value => String(value) }, '@/composables/useTableView': { useTableView: () => ({ visibleKeys: Vue.ref([]), density: Vue.ref('default'), panelRef: Vue.ref(null) }) }, '@/components/TableTools.vue': { default: slotShell }, './KnowledgeDocumentPreview.vue': { default: slotShell } }
}
function registrations() {
  const names = ['el-timeline', 'el-timeline-item', 'el-table-column', 'el-form', 'el-form-item', 'el-input', 'el-select', 'el-option', 'el-input-number', 'el-switch', 'el-progress', 'el-tabs', 'el-tab-pane', 'el-radio-group', 'el-radio-button']
  const result = Object.fromEntries(names.map(name => [name, slotShell])); return { ...result, ListPageStatus: status, GlassButton: button, StatusBadge: slotShell, DetailDrawer: visibleShell, 'el-dialog': visibleShell, 'el-alert': slotShell, 'el-empty': { props: ['description'], setup: props => () => Vue.h('p', props.description) }, 'el-table': { props: ['data'], setup: (props, { slots }) => () => Vue.h('section', props.data.length ? props.data.map(row => Vue.h('p', row.name || String(row.id))) : slots.empty?.()) } }
}

test('mounted AI settings initial list error has a working retry and stale successful rows stay visible', async t => {
  let failed = true, reads = 0
  const component = loadComponent('../../src/views/knowledge/KnowledgeAiSettings.vue', mountedModules({ listAiProfiles: async () => { reads++; if (failed) throw new Error('mounted profile offline'); return { data: [{ id: 1, name: 'Retained profile' }] } } }))
  const mounted = mountComponent(t, component, {}, undefined, registrations()); await flush(); assert.match(mounted.text(), /mounted profile offline/); assert.doesNotMatch(mounted.text(), /暂无数据/); failed = false; mounted.find(node => node.type === 'button' && node.props.onClick).at(-1).props.onClick(); await flush(); assert.equal(reads, 2); assert.match(mounted.text(), /Retained profile/)
  failed = true; mounted.find(node => node.props?.onRefresh)[0].props.onRefresh(); await flush(); assert.match(mounted.text(), /Retained profile/); assert.match(mounted.text(), /可能已过期/)
})

test('mounted optimization history first failure exposes exact retry and visible recent thirty boundary', async t => {
  let failed = true, reads = 0
  const component = loadComponent('../../src/views/knowledge/components/AiOptimizationDrawer.vue', mountedModules({ listAiProfiles: async () => ({ data: [{ id: 4, name: 'Fixture', config_version: 1 }] }), listDocumentAiJobs: async id => { reads++; assert.equal(id, 7); if (failed) throw new Error('mounted history offline'); return { data: [] } } }))
  const mounted = mountComponent(t, component, { modelValue: true, document: { id: 7, library_id: 3, revision_id: 70 }, dirty: false }, undefined, registrations()); await flush(); assert.match(mounted.text(), /最近 30 条/); assert.match(mounted.text(), /mounted history offline/); const start = mounted.find(node => node.type === 'button').at(-1); assert.equal(start.props.disabled, true); failed = false; mounted.find(node => node.type === 'button')[0].props.onClick(); await flush(); assert.equal(reads, 2); assert.doesNotMatch(mounted.text(), /mounted history offline/); assert.equal(mounted.find(node => node.type === 'button').at(-1).props.disabled, false)
})
