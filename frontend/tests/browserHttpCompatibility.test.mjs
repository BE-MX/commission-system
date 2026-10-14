import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, existsSync } from 'node:fs'
import vm from 'node:vm'
import { webcrypto } from 'node:crypto'

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
function loadUtility(context, name) {
  const path = new URL(`../src/utils/${name}.js`, import.meta.url)
  if (existsSync(path)) vm.runInContext(readFileSync(path, 'utf8').replace(/export /g, ''), context)
}
function linked(api) {
  const context = vm.createContext({ ref: value => ({ value }), msgWarning() {},
    crypto: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) },
    saveInvoiceLinked: api })
  loadUtility(context, 'requestKey')
  const source = read('../src/views/invoice/composables/useLinkedInvoiceSync.js')
    .replace(/^import .*$/gm, '').replace('export function', 'function')
  vm.runInContext(source + '\nthis.linked = useLinkedInvoiceSync()', context)
  return context.linked
}

test('LAN HTTP linked save reaches API and lost response retries original body/key', async () => {
  const requests = [], model = linked(async (id, body) => {
    requests.push(body)
    if (requests.length === 1) throw Error('Simulated lost response')
    return { invoice: { id }, operation: { id: 'op', invoice_id: id } }
  })
  await assert.rejects(model.save(1, { amount: 100 }, 'v1'), /Simulated lost response/)
  assert.equal(requests.length, 1)
  assert.match(requests[0].request_key, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
  assert.equal(await model.save(1, { amount: 200 }, 'v2'), null)
  assert.equal(requests.length, 2)
  assert.equal(requests[0], requests[1])
})

function clipboardContext(result = true, navigator = {}) {
  const nodes = [], successes = [], errors = [], copied = []
  const active = { focus() {} }
  const document = { activeElement: active, getSelection: () => null,
    createElement: () => ({ style: {}, setAttribute() {}, focus() {}, select() {}, setSelectionRange() {},
      remove() { nodes.splice(nodes.indexOf(this), 1) } }),
    body: { appendChild: node => nodes.push(node) },
    execCommand: () => { copied.push(nodes[0]?.value); return result } }
  const context = vm.createContext({ navigator, document,
    msgSuccessText: text => successes.push(text), msgError: text => errors.push(text) })
  loadUtility(context, 'clipboard')
  const source = read('../src/views/tracking/TrackingList.vue')
  const start = source.search(/(?:async )?function copyLink\(link\)/), end = source.indexOf('\nfunction fmtDateShort', start)
  vm.runInContext(source.slice(start, end), context)
  return { context, nodes, successes, errors, copied }
}

test('LAN HTTP tracking copy uses selected-text copy and reports verified success', async () => {
  const state = clipboardContext()
  await state.context.copyLink('https://example.test/tracking')
  assert.deepEqual(state.copied, ['https://example.test/tracking'])
  assert.equal(state.successes.length, 1)
  assert.equal(state.nodes.length, 0)
})

test('blocked copy gives manual-copy feedback without a false success', async () => {
  const state = clipboardContext(false)
  await state.context.copyLink('https://example.test/tracking')
  assert.equal(state.successes.length, 0)
  assert.equal(state.errors.length, 1)
  assert.equal(state.nodes.length, 0)
})

test('HTTP request keys use secure entropy, preserve UUID bits, and do not repeat', () => {
  const context = vm.createContext({ crypto: { getRandomValues: webcrypto.getRandomValues.bind(webcrypto) } })
  loadUtility(context, 'requestKey')
  const keys = new Set()
  for (let i = 0; i < 1000; i++) {
    const key = context.newRequestKey()
    assert.match(key, /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/)
    keys.add(key)
  }
  assert.equal(keys.size, 1000)
  const unavailable = vm.createContext({ crypto: {} })
  loadUtility(unavailable, 'requestKey')
  assert.throws(() => unavailable.newRequestKey(), /getRandomValues/)
})

test('HTTPS native clipboard succeeds without changing selection or adding a node', async () => {
  const native = [], state = clipboardContext(false, { clipboard: { writeText: async text => native.push(text) } })
  await state.context.copyLink('native-copy')
  assert.deepEqual(native, ['native-copy'])
  assert.equal(state.copied.length, 0)
  assert.equal(state.successes.length, 1)
})

test('native clipboard permission rejection uses the HTTP copy fallback', async () => {
  const state = clipboardContext(true, { clipboard: { writeText: async () => { throw Error('Permission denied') } } })
  await state.context.copyLink('fallback-copy')
  assert.deepEqual(state.copied, ['fallback-copy'])
  assert.equal(state.successes.length, 1)
})

test('copy restores the original input focus and selected range', async () => {
  const state = clipboardContext(), restored = []
  state.context.document.activeElement = { selectionStart: 2, selectionEnd: 4, selectionDirection: 'backward',
    focus: () => restored.push('focus'), setSelectionRange: (...args) => restored.push(args) }
  await state.context.copyLink('selection-copy')
  assert.deepEqual(restored, ['focus', [2, 4, 'backward']])
  assert.equal(state.nodes.length, 0)
})

test('copy restores selected document text and cleans up even if fallback throws', async () => {
  const state = clipboardContext(), restored = [], savedRange = { marker: 'original' }
  state.context.document.getSelection = () => ({ rangeCount: 1, getRangeAt: () => ({ cloneRange: () => savedRange }),
    removeAllRanges: () => restored.push('clear'), addRange: range => restored.push(range) })
  state.context.document.execCommand = () => { throw Error('Browser blocked copy') }
  await state.context.copyLink('blocked-copy')
  assert.equal(state.successes.length, 0)
  assert.equal(state.errors.length, 1)
  assert.deepEqual(restored, ['clear', savedRange])
  assert.equal(state.nodes.length, 0)
})

test('mobile manual-copy prompt does not report automatic success', async () => {
  const source = read('../public/m/index.html'), start = source.indexOf('async function copyShareLink(url)'), end = source.indexOf('\n}', start) + 2
  const prompts = [], context = vm.createContext({ copyText: async () => false,
    window: { prompt: (...args) => prompts.push(args) } })
  vm.runInContext(source.slice(start, end), context)
  assert.equal(await context.copyShareLink('https://example.test/share'), false)
  assert.equal(prompts[0][1], 'https://example.test/share')
})

test('all four mobile copy actions stop success status and audit when automatic copy fails', async () => {
  const source = read('../public/m/index.html')
  const methods = [...source.matchAll(/    async function copyLink\(([^)]*)\) \{([\s\S]*?)\n    \}/g)]
  assert.equal(methods.length, 4)
  for (const method of methods) {
    const messages = [], actions = []
    const context = vm.createContext({ copyShareLink: async () => false,
      API: { getShareLink: async () => ({ url: 'https://example.test/share' }), recordAction: (...args) => { actions.push(args); return Promise.resolve() } },
      asset: { value: { id: 1 } }, copied: { value: false }, setTimeout() {},
      toast: { show: (...args) => messages.push(args) } })
    vm.runInContext(`async function copyLink(${method[1]}) {${method[2]}\n}`, context)
    await context.copyLink({ id: 1 })
    assert.equal(context.copied.value, false)
    assert.equal(actions.length, 0)
    assert.equal(messages.length, 1)
    assert.equal(messages[0][1], 'error')
  }
})
