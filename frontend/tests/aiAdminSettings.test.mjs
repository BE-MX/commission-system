import test from 'node:test'
import assert from 'node:assert/strict'
import { viewController } from './helpers/viewController.mjs'
import * as fields from '../src/views/system/aiConfigFields.js'

test('nested runtime edits preserve vendor keys and clearing a field restores inheritance', () => {
  const original = JSON.stringify({ request_parameters: { seed: 7 }, transport: { image_timeout_sec: 40 } })
  const changed = fields.setConfigValue(original, 'transport.connect_timeout_sec', 3)
  assert.deepEqual(JSON.parse(changed), { request_parameters: { seed: 7 }, transport: { image_timeout_sec: 40, connect_timeout_sec: 3 } })
  assert.deepEqual(JSON.parse(fields.setConfigValue(changed, 'transport.connect_timeout_sec', null)), JSON.parse(original))
  assert.throws(() => fields.setConfigValue('{bad', 'transport.timeout_sec', 3))
  assert.throws(() => fields.setConfigValue('{"transport":[]}', 'transport.timeout_sec', 3))
})

test('provider form preserves address across type changes and saves parsed runtime and headers', async t => {
  let saved
  const { vm } = viewController(t, '../../src/views/system/composables/useAiManager.js', 'useAiManager', { '@/api/ai': {
    updateProvider: async (id, payload) => { saved = { id, payload } },
    getProviders: async () => ({ data: { items: [] } }),
  } })
  const state = vm.useAiManager()
  const row = { id: 1, name: 'provider', api_base: 'https://chosen.test/v1', runtime_config: { image_timeout_sec: 35 }, extra_headers: { 'X-Project': 'ark' } }
  state.openProviderDialog(row)
  state.onProviderTypeChange('accio_work')
  assert.equal(state.providerForm.value.api_base, row.api_base)
  state.providerFormRef.value = { validate: async () => true }
  state.providerForm.value.runtime_config = fields.setConfigValue(state.providerForm.value.runtime_config, 'image_edit_path', 'edit')
  await state.submitProvider()
  assert.deepEqual(saved.payload.runtime_config, { image_timeout_sec: 35, image_edit_path: 'edit' })
  assert.deepEqual(saved.payload.extra_headers, { 'X-Project': 'ark' })
  assert.equal('api_key' in saved.payload, false)
  state.openProviderDialog(saved.payload)
  assert.equal(JSON.parse(state.providerForm.value.runtime_config).image_edit_path, 'edit')
})

for (const key of ['runtime_config', 'extra_headers']) {
  test(`invalid ${key} cannot overwrite saved provider settings`, async t => {
    let writes = 0
    const { vm } = viewController(t, '../../src/views/system/composables/useAiManager.js', 'useAiManager', { '@/api/ai': {
      updateProvider: async () => { writes++ },
    } })
    const state = vm.useAiManager()
    state.openProviderDialog({ id: 1, runtime_config: { image_timeout_sec: 35 }, extra_headers: {} })
    state.providerFormRef.value = { validate: async () => true }
    state.providerForm.value[key] = '{bad'
    await state.submitProvider()
    assert.equal(writes, 0)
    assert.equal(state.providerDialogVisible.value, true)
    assert.equal(state.providerSaving.value, false)
  })
}

test('typed JSON errors emit invalidity and never silently replace saved parameters', t => {
  const { vm, messages } = viewController(t, '../../src/views/system/components/AiConfigFields.vue', 'update, errors', {
    '@props': { modelValue: '{"download_hosts":["image.test"],"temperature":0.4}' },
    '../aiConfigFields': fields,
  })
  vm.update({ key: 'download_hosts', type: 'json' }, '[bad')
  assert.equal(messages.at(-1).event, 'validity')
  assert.equal(messages.at(-1).args[0], false)
  assert.equal(messages.some(item => item.event === 'update:modelValue'), false)
  vm.update({ key: 'download_hosts', type: 'json' }, '["new.test"]')
  const saved = messages.find(item => item.event === 'update:modelValue')
  assert.deepEqual(JSON.parse(saved.args[0]), { download_hosts: ['new.test'], temperature: 0.4 })
  assert.equal(messages.at(-1).args[0], true)
})
