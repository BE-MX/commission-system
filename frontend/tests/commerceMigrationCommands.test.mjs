import test from 'node:test'
import assert from 'node:assert/strict'
import { useMigrationImport } from '../src/views/commerce-migration/useMigrationImport.js'
import { useMigrationActivation } from '../src/views/commerce-migration/useMigrationActivation.js'

const body = { batch_key: 'reviewed-1', source: 'okki', tenant: 'verified-account', cutover_date: '2026-10-03',
  evidence_sha256: 'a'.repeat(64), review_reference: 'Synthetic reviewed file', catalog: [],
  archives: [{ object_type: 'order', external_id: 'OLD-1', snapshot: { amount: '1000' } }] }
const file = (value = body, name = 'reviewed.json') => ({ name, size: 400, text: async () => JSON.stringify(value) })
const ready = { data: { can_apply: true, conflicts: [] } }

test('reviewed pending material files use their dedicated command type and reject mixed responsibilities', async () => {
  const seen = []
  const command = useMigrationImport({ preview: async (kind, payload) => { seen.push({ kind, payload }); return ready },
    apply: async (_, payload) => ({ data: { batch_key: payload.batch_key, resolutions: [] } }) })
  const { catalog, archives, ...identity } = body
  await command.readFile(file({ ...identity, resolutions: [{ invoice_id: 5, outcome: 'not_accepted' }] }))
  assert.equal(command.kind.value, 'pendingMaterials')
  assert.equal(await command.preview(), true)
  assert.equal(seen[0].kind, 'pendingMaterials')
  await command.readFile(file({ ...identity, resolutions: [], materials: [] }))
  assert.equal(command.manifest.value, null)
  assert.match(command.failure.value, /类型不明确/)
})

test('preview is read-only; an uncertain import keeps the exact file identity and forbids replacement', async () => {
  const sends = [], previews = []
  let attempts = 0
  const command = useMigrationImport({ preview: async (kind, payload) => { previews.push({ kind, payload }); return ready },
    apply: async (kind, payload) => { sends.push({ kind, payload }); if (++attempts === 1) throw new Error('Response lost'); return { data: { batch_key: payload.batch_key, archives: [] } } } })
  await command.readFile(file())
  assert.equal(command.kind.value, 'catalog')
  assert.equal(await command.apply(), false)
  await command.preview()
  assert.equal(sends.length, 0)
  await command.apply()
  assert.equal(command.uncertain.value, true)
  assert.equal(command.clear(), false)
  await command.readFile(file({ ...body, batch_key: 'new-identity' }))
  assert.equal(command.manifest.value.batch_key, body.batch_key)
  assert.equal(await command.preview(), false)
  assert.equal(previews.length, 1)
  assert.equal(await command.apply(), true)
  assert.deepEqual(sends[0], sends[1])
  assert.equal(command.uncertain.value, false)
  assert.equal(await command.apply(), false)
  assert.equal(sends.length, 2)
})

test('server conflicts and incomplete previews never enable import; explicit rejection requires new preview', async () => {
  let calls = 0, preview = { data: { can_apply: false, conflicts: [{ message: 'Missing original cash' }] } }
  const command = useMigrationImport({ preview: async () => preview,
    apply: async () => { calls++; throw { response: { status: 409, data: { detail: 'Source changed' } } } } })
  await command.readFile(file()); await command.preview(); await command.apply()
  assert.equal(calls, 0)
  preview = { data: { can_apply: true } }
  assert.equal(await command.preview(), false)
  assert.equal(command.canApply.value, false)
  preview = ready
  await command.preview(); await command.apply()
  assert.equal(calls, 1)
  assert.equal(command.uncertain.value, false)
  assert.equal(command.report.value, null)
  assert.equal(await command.apply(), false)
})

test('invalid replacement clears the old accepted file, and simultaneous import sends once', async () => {
  let release, calls = 0
  const command = useMigrationImport({ preview: async () => ready,
    apply: payload => { calls++; return new Promise(resolve => { release = () => resolve({ data: { batch_key: body.batch_key } }) }) } })
  await command.readFile(file()); await command.preview()
  await command.readFile({ name: 'invalid.json', size: 20, text: async () => '{' })
  assert.equal(command.manifest.value, null)
  assert.equal(command.canApply.value, false)
  await command.readFile(file()); await command.preview()
  const first = command.apply(), second = command.apply()
  release(); await Promise.all([first, second])
  assert.equal(calls, 1)
})

function activationApi({ send, prepare } = {}) {
  return { prepare: prepare || (async selection => ({ data: { command: { request_key: selection.request_key,
    business_date: '2026-10-03', orders: [{ order_binding_record_id: selection.record_ids[0], expected_version: 7 }], productions: [] },
    descriptions: [{ name: 'ORIGINAL-INVOICE', target_id: 100 }], report: { can_activate: true, conflicts: [] } } })),
  activate: send || (async payload => ({ data: { request_key: payload.request_key } })) }
}

test('activation response loss preserves prepared IDs and versions, including retries after selection changes', async () => {
  const sent = [], prepared = []
  const api = activationApi({ send: async payload => { sent.push(structuredClone(payload)); if (sent.length === 1) throw new Error('Response lost'); return { data: { request_key: payload.request_key } } } })
  const prepare = api.prepare
  api.prepare = async payload => { prepared.push(payload); return prepare(payload) }
  const command = useMigrationActivation(api, () => 'stable-prepared-key')
  await command.prepare([9]); await command.activate()
  assert.equal(command.uncertain.value, true)
  assert.equal(command.clear(), false)
  assert.equal(await command.prepare([10]), false)
  assert.equal(prepared.length, 1)
  assert.equal(await command.activate(), true)
  assert.deepEqual(sent[0], sent[1])
  assert.equal(sent[1].orders[0].expected_version, 7)
  assert.equal(await command.activate(), false)
})

test('activation conflict discards obsolete versions and repeated clicks cannot send twice', async () => {
  const command = useMigrationActivation(activationApi({ send: async () => { throw { response: { status: 409, data: { detail: 'Version changed' } } } } }), () => 'version-key')
  await command.prepare([9]); await command.activate()
  assert.equal(command.review.value, null)
  assert.equal(command.uncertain.value, false)
  assert.equal(await command.activate(), false)
  let release, calls = 0
  const concurrent = useMigrationActivation(activationApi({ send: payload => { calls++; return new Promise(resolve => { release = () => resolve({ data: { request_key: payload.request_key } }) }) } }), () => 'once-key')
  await concurrent.prepare([9])
  const first = concurrent.activate(), second = concurrent.activate()
  release(); await Promise.all([first, second])
  assert.equal(calls, 1)
})

test('key generation failures and malformed readiness responses do not leave activation pending or enabled', async () => {
  const command = useMigrationActivation(activationApi(), () => { throw new Error('Secure key unavailable') })
  assert.equal(await command.prepare([9]), false)
  assert.equal(command.pending.value, false)
  assert.equal(command.review.value, null)
  const malformed = useMigrationActivation(activationApi({ prepare: async () => ({ data: {} }) }), () => 'safe-key')
  assert.equal(await malformed.prepare([9]), false)
  assert.equal(await malformed.activate(), false)
})

test('legacy settlement uses the exact reviewed request, invoice epochs and bank identities without fabricated closing facts', async () => {
  const original = { request_key: 'settlement-reviewed-1', evidence_sha256: 'd'.repeat(64), review_reference: 'Approved original closing ledger',
    invoices: [{ invoice_id: 8, expected_authority_epoch: 3 }], bank_identity_ids: [11] }
  const sent = []
  const command = useMigrationImport({ preview: async (kind, payload) => {
    assert.equal(kind, 'legacy_settlement'); assert.deepEqual(payload, original); return ready
  }, apply: async (kind, payload) => { sent.push({ kind, payload }); return { data: { request_key: original.request_key, settled: true } } } })
  await command.readFile(file(original)); assert.equal(command.kind.value, 'legacy_settlement')
  await command.preview(); assert.equal(await command.apply(), true)
  assert.deepEqual(sent, [{ kind: 'legacy_settlement', payload: original }])
  await command.readFile(file({ ...original, payments: [] }))
  assert.equal(command.manifest.value, null)
  assert.match(command.failure.value, /类型不明确/)
})

test('waiting handover freezes the original file and never reports import success; only same request can resume', async () => {
  const original = { ...body, orders: [{ invoice_id: 7 }] }; delete original.catalog; delete original.archives
  const sent = []
  const command = useMigrationImport({ preview: async () => ready, apply: async (_, payload) => {
    sent.push(structuredClone(payload))
    return { data: sent.length === 1 ? { status: 'waiting', handover_preparation_id: 9, orders: [], message: 'Original claim unresolved' }
      : { batch_key: original.batch_key, orders: [{ invoice_id: 7 }] } }
  } })
  await command.readFile(file(original)); await command.preview()
  assert.equal(await command.apply(), false)
  assert.equal(command.waiting.value, true); assert.equal(command.locked.value, true)
  assert.equal(command.clear(), false)
  await command.readFile(file({ ...body, batch_key: 'different' }))
  assert.equal(command.manifest.value.batch_key, original.batch_key)
  assert.equal(await command.preview(), false)
  assert.equal(await command.apply(), true)
  assert.equal(command.waiting.value, false)
  assert.deepEqual(sent[0], sent[1])
})
