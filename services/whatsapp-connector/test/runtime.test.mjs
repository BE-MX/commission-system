import assert from 'node:assert/strict'
import test from 'node:test'
import { readFileSync } from 'node:fs'
import makeWASocket, { initAuthCreds } from 'baileys'
import { generateKeyPair, getEnabledFeatures, __wasmSimdActive } from 'whatsapp-rust-bridge'

test('pinned Baileys and installed Rust/WASM bridge execute on the actual Node runtime without a browser', () => {
  const manifest = JSON.parse(readFileSync(new URL('../package-lock.json', import.meta.url)))
  assert.equal(manifest.packages['node_modules/baileys'].version, '7.0.0-rc14')
  assert.equal(manifest.packages['node_modules/whatsapp-rust-bridge'].version, '0.5.4')
  assert.equal(typeof makeWASocket, 'function')
  assert.equal(initAuthCreds().noiseKey.private.length, 32)
  const pair = generateKeyPair()
  assert.equal(pair.privKey.length, 32)
  assert.ok(pair.pubKey.length >= 32)
  assert.equal(typeof __wasmSimdActive, 'boolean')
  assert.equal(typeof getEnabledFeatures().image, 'boolean')
  assert.equal(Object.keys(manifest.packages).some(name => /puppeteer|chromium|whatsapp-web\.js/.test(name)), false)
})
