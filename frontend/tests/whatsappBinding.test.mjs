import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'
import vm from 'node:vm'

async function bindingFixture() {
  let response = 'pending', requests = 0
  const timers = new Set()
  const context = vm.createContext({
    setTimeout(fn) { timers.add(fn); return fn },
    clearTimeout(fn) { timers.delete(fn) },
  })
  const responseFor = () => ({ data: { bind_session_uid: 'synthetic-bind', status: response } })
  const imports = {
    vue: { ref: value => ({ value }), computed: fn => ({ get value() { return fn() } }), watch: () => {}, onUnmounted: () => {} },
    '@/api/whatsapp': {
      createWhatsAppBindSession: async () => responseFor(),
      getWhatsAppBindSession: async () => { requests++; return responseFor() },
      updateWhatsAppConsent: async () => {}, listWhatsAppReaderCandidates: async () => ({ data: [] }),
    },
    '@/utils/feedback': { msgSuccessText: () => {}, msgWarning: () => {} },
  }
  const source = await readFile(new URL('../src/views/system/composables/useWhatsAppBinding.js', import.meta.url), 'utf8')
  const module = new vm.SourceTextModule(source, { context })
  await module.link(name => new vm.SyntheticModule(Object.keys(imports[name]), function () {
    for (const [key, value] of Object.entries(imports[name])) this.setExport(key, value)
  }, { context }))
  await module.evaluate()
  const binding = module.namespace.useWhatsAppBinding(async () => {})
  binding.openBind()
  binding.companyAccount.value = true
  return { binding, timers, setStatus(value) { response = value }, requests: () => requests }
}

for (const status of ['paused', 'blocked', 'revoking', 'revoke_pending', 'revoked', 'reconnect_required']) {
  test(`binding stops automatic status queries after ${status}`, async () => {
    const fixture = await bindingFixture()
    await fixture.binding.create()
    assert.equal(fixture.timers.size, 1, 'pending should continue waiting for QR')
    fixture.setStatus(status)
    await fixture.binding.refresh()
    assert.equal(fixture.requests(), 1)
    assert.equal(fixture.binding.bindSession.value.status, status)
    assert.equal(fixture.timers.size, 0, 'stopped binding must not keep querying/auditing')
  })
}

test('unlinked chat AI switch is only available on top of consent, CRM sharing and AI egress', async () => {
  const { binding } = await bindingFixture()
  binding.consentForm.value = { enabled: true, crm_shared: true, ai_egress_allowed: false, unlinked_ai_allowed: false }
  assert.equal(binding.unlinkedAiAvailable.value, false)
  binding.consentForm.value = { enabled: true, crm_shared: true, ai_egress_allowed: true, unlinked_ai_allowed: false }
  assert.equal(binding.unlinkedAiAvailable.value, true)
  binding.consentForm.value = { enabled: false, crm_shared: true, ai_egress_allowed: true, unlinked_ai_allowed: true }
  assert.equal(binding.unlinkedAiAvailable.value, false)
})
