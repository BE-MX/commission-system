import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { computed, reactive, ref } from 'vue'
import { usePromptVersions } from '../src/views/expo/composables/usePromptVersions.js'

const options = [{ id: 12, name: '真实', is_default: false }, { id: 91, name: '自定义版本', is_default: true }]
test('database default, arbitrary IDs and selection survive refresh', async () => {
  let values = options
  const state = usePromptVersions(async () => ({ data: values }))
  await state.loadPromptVersions()
  assert.equal(state.promptVersionId.value, 91)
  state.promptVersionId.value = 12
  values = [...options, { id: 245, name: '新版本' }]
  await state.loadPromptVersions()
  assert.equal(state.promptVersionId.value, 12)
  assert.equal(state.promptVersions.value.length, 3)
  state.promptVersionId.value = 245
  assert.equal(state.promptVersionReady.value, true)
  values = options
  await state.loadPromptVersions()
  assert.equal(state.promptVersionId.value, 91)
})
test('empty and failed options block generation', async () => {
  let fail = false
  const state = usePromptVersions(async () => { if (fail) throw Error('network'); return { data: [] } })
  await state.loadPromptVersions()
  assert.equal(state.promptVersionReady.value, false)
  assert.match(state.promptVersionsError.value, /暂无/)
  fail = true
  await state.loadPromptVersions()
  assert.equal(state.promptVersionReady.value, false)
  assert.match(state.promptVersionsError.value, /重试/)
})
test('late response cannot contaminate next customer or newer refresh', async () => {
  const pending = []
  const state = usePromptVersions(() => new Promise(resolve => pending.push(resolve)))
  const old = state.loadPromptVersions()
  state.resetPromptVersions()
  pending.shift()({ data: options }); await old
  assert.deepEqual(state.promptVersions.value, [])
  const first = state.loadPromptVersions(), second = state.loadPromptVersions()
  pending[1]({ data: options }); await second
  pending[0]({ data: [{ id: 999 }] }); await first
  assert.equal(state.promptVersionId.value, 91)
})
function flowWith(api) {
  const source = readFileSync(new URL('../src/views/expo/composables/useTryOnFlow.js', import.meta.url), 'utf8')
    .replace(/^import [\s\S]*? from ['"][^'"]+['"]\s*$/gm, '').replace('export function', 'function')
  const noop = () => {}
  const deps = { computed, reactive, ref, onBeforeUnmount: noop, normalisePhone: x => x, usePromptVersions,
    useAiIssueSupport: () => ({ aiIssue: ref(null), resetAiIssueSupport: noop }),
    useQrUpload: () => ({ qrUrl: ref(null), pendingName: ref(''), closeQr: noop, disposeQr: noop }),
    createSession: noop, generateResults: noop, getScenes: noop, getSession: () => new Promise(noop),
    getWigColors: noop, registerCustomer: noop, setReaction: noop, submitFeedback: noop, updateCustomer: noop,
    getPromptVersionPicker: async () => ({ data: options }), ...api }
  return Function(...Object.keys(deps), source + '; return useTryOnFlow()')(...Object.values(deps))
}
for (const mode of ['tryon', 'scene']) {
  test(`${mode}: chosen ID reaches generate`, async () => {
    const sent = []
    const flow = flowWith({ generateResults: async (...args) => sent.push(args) })
    flow.sessionId.value = 44; flow.mode.value = mode
    flow.selectedWigId.value = 8; flow.selectedSceneKeys.value = ['cafe']
    await flow.loadPromptVersions(); flow.promptVersionId.value = 12
    await (mode === 'scene' ? flow.generateScenes() : flow.generate())
    assert.equal(sent[0][1].promptVersionId, 12)
    assert.equal(flow.step.value, 'result')
    flow.resetAll()
    assert.equal(flow.promptVersionId.value, null)
  })
  test(`${mode}: stopped version returns to picker with backend message`, async () => {
    const flow = flowWith({ generateResults: async () => { throw { response: { status: 409, data: { detail: '版本已停用' } } } } })
    flow.sessionId.value = 44; flow.mode.value = mode
    flow.selectedWigId.value = 8; flow.selectedSceneKeys.value = ['cafe']
    await flow.loadPromptVersions()
    await (mode === 'scene' ? flow.generateScenes() : flow.generate())
    assert.equal(flow.step.value, mode === 'scene' ? 'scene' : 'matching')
    assert.equal(flow.errorText.value, '版本已停用')
    assert.equal(flow.generating.value, false)
    flow.resetAll()
  })
}
test('API submits current contract', () => {
  const source = readFileSync(new URL('../src/api/expo.js', import.meta.url), 'utf8')
  assert.match(source, /prompt_version_id: promptVersionId/)
  assert.doesNotMatch(source, /prompt_variant:/)
})
