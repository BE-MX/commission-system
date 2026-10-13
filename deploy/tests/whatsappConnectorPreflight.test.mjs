import test from 'node:test'
import assert from 'node:assert/strict'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const script = fileURLToPath(new URL('../whatsapp_connector_preflight.mjs', import.meta.url))
const source = fileURLToPath(new URL('../../services/whatsapp-connector', import.meta.url))
const env = { WHATSAPP_CONNECTOR_API_KEY: 'synthetic-private-key',
  WHATSAPP_ENCRYPTION_KEY: Buffer.alloc(32, 17).toString('base64'),
  ARK_API_BASE_URL: 'http://127.0.0.1:1', WHATSAPP_PROVIDER: 'baileys' }
function check(settings) {
  return spawnSync(process.execPath, [script], { input: JSON.stringify({ source, env: settings }), encoding: 'utf8', timeout: 20000 })
}
test('candidate actually starts with isolated state without contacting Ark or restoring accounts', () => {
  const result = check(env)
  assert.equal(result.status, 0, result.stderr)
  assert.match(result.stdout, /isolated startup verified/)
  assert.ok(!result.stdout.includes(env.WHATSAPP_CONNECTOR_API_KEY))
})
for (const field of ['WHATSAPP_ENCRYPTION_KEY', 'ARK_API_BASE_URL', 'WHATSAPP_CONNECTOR_API_KEY']) {
  test(`missing ${field} blocks before release with no leaked secret`, () => {
    const result = check({ ...env, [field]: '' })
    assert.equal(result.status, 1)
    assert.ok(!result.stdout.includes('isolated startup verified'))
    assert.ok(!result.stderr.includes(env.WHATSAPP_CONNECTOR_API_KEY))
  })
}
