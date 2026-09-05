import test from 'node:test'
import assert from 'node:assert/strict'
import { parseRuleDocument, ruleDocument, COUNTRY_OPTIONS } from '../src/views/customer_hub/poolRuleEditor.js'
import { createCustomerHubApi } from '../src/api/customerHubContract.js'

const example = () => ({
  rules: { schema_version: 'public_pool_selection_v2', commerce: { min_orders: 2, total_usd_gt: 1500, single_usd_gt: 1000, allow_sample_only: true, sample_requires_product: true }, countries: COUNTRY_OPTIONS.map(([code]) => code), contact_channels: ['instagram', 'facebook', 'phone'], prefer_instagram: true, product_terms: ['genius weft', '平型', '贴发'], product_exclusions: ['胶'], no_order_days: 180, no_followup_days: 30, missing_followup: 'exclude' },
  quotas: { schema_version: 'public_pool_quotas_v1', tiers: { T1: 20, T2: 20, T3: 20 }, team_scope: 'all', total_limit: 60 },
})

test('visual settings round trip through JSON without losing the sample product switch', () => {
  const config = example()
  config.rules.commerce.sample_requires_product = false
  config.rules.countries.push('us')
  const parsed = parseRuleDocument(JSON.stringify(config))
  assert.equal(parsed.rules.countries.length, 13)
  assert.equal(parsed.rules.commerce.sample_requires_product, false)
  const copy = ruleDocument(parsed)
  copy.rules.no_order_days = 365
  assert.equal(parsed.rules.no_order_days, 180)
  assert.deepEqual(parseRuleDocument(JSON.stringify(copy)), copy)
})

for (const [name, change] of [
  ['unknown rule', c => { c.rules.auto_send = true }],
  ['unknown nested setting', c => { c.rules.commerce.extra = 1 }],
  ['negative quota', c => { c.quotas.tiers.T1 = -1 }],
  ['zero quotas', c => { c.quotas.tiers = { T1: 0, T2: 0, T3: 0 } }],
  ['empty channels', c => { c.rules.contact_channels = [] }],
  ['empty normalized product', c => { c.rules.product_terms = ['---'] }],
  ['invalid country', c => { c.rules.countries = ['USA'] }],
  ['string boolean', c => { c.rules.prefer_instagram = 'false' }],
]) test(`reject ${name} before replacing visual form`, () => {
  const config = example(); change(config)
  assert.throws(() => parseRuleDocument(JSON.stringify(config)))
})

test('rules API preserves optimistic version and preview payload', async () => {
  const calls = []
  const client = Object.fromEntries(['get', 'put', 'post'].map(method => [method, (...args) => { calls.push([method, ...args]); return Promise.resolve({ data: {} }) }]))
  const api = createCustomerHubApi(client), payload = { ...example(), expected_version: 3 }
  await api.getPublicPoolRules(); await api.savePublicPoolRules(payload)
  await api.previewPublicPoolRules(example()); await api.createConfiguredPublicPoolBatch({ expected_version: 3 })
  assert.deepEqual(calls.map(c => c.slice(0, 2)), [['get', '/public-pool/rules'], ['put', '/public-pool/rules'], ['post', '/public-pool/rules/preview'], ['post', '/public-pool/rules/batches']])
  assert.equal(calls[1][2], payload)
  assert.deepEqual(calls[3][2], { expected_version: 3 })
})
