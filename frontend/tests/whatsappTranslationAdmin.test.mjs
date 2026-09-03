import assert from 'node:assert/strict'
import test from 'node:test'

import { healthLabel, parseReleaseManifest, sanitizeDeviceRows } from '../src/views/system/whatsappTranslationAdmin.js'

test('maps health and device status to concise labels', () => {
  assert.equal(healthLabel({ request_count: 3, success_count: 2 }), '66.7%')
  assert.equal(healthLabel({ request_count: 0, success_count: 0 }), '—')
})

test('accepts only the exact internal release manifest shape', () => {
  const release = {
    extension_id: 'bnkecbkoidckffckbefjjcbchmngjobi',
    filename: 'whatsapp-translation-1.0.0.zip',
    sha256: 'a'.repeat(64),
    size: 1024,
    version: '1.0.0',
  }
  assert.deepEqual(parseReleaseManifest(release), release)
  assert.throws(() => parseReleaseManifest({ ...release, extra: true }))
  assert.throws(() => parseReleaseManifest({ ...release, filename: 'evil/../x.zip' }))
})

test('serialized device rows never contain private message or credential keys', () => {
  const rows = sanitizeDeviceRows([{
    browser_name: 'Chrome',
    device_id: 7,
    token: 'secret',
    token_hash: 'hash',
    text: 'message',
    translation: 'translation',
    contact: 'contact',
    phone: 'phone',
  }])

  const keys = Object.keys(rows[0])
  for (const forbidden of ['token', 'token_hash', 'text', 'translation', 'contact', 'phone']) {
    assert.equal(keys.includes(forbidden), false)
  }
})
