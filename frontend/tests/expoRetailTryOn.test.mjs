import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const root = path.resolve(import.meta.dirname, '..')
const sessionModule = await import(pathToFileURL(path.join(root, 'src/views/expo/retailTryOnSession.js')))

function memoryStorage() {
  const data = new Map()
  return {
    getItem: key => data.get(key) ?? null,
    setItem: (key, value) => data.set(key, String(value)),
  }
}

test('retail grant is captured from the fragment and never remains in the visible URL', () => {
  const storage = memoryStorage()
  let replaced = ''
  const grant = '0e68f8e0-c464-4c10-8b4f-e4e45200f90c'
  const accepted = sessionModule.captureRetailTryOnSession({
    location: {
      pathname: '/expo/retail',
      hash: `#grant=${grant}&return=${encodeURIComponent('https://leshine-wig-platform.pages.dev/retail')}`,
    },
    history: { state: null, replaceState: (_state, _unused, url) => { replaced = url } },
    storage,
  })
  assert.equal(accepted, true)
  assert.equal(sessionModule.getRetailTryOnAuthorization(storage), `Retail ${grant}`)
  assert.equal(replaced, '/expo/retail')
})

test('return target is restricted to the retail mall', () => {
  const storage = memoryStorage()
  sessionModule.captureRetailTryOnSession({
    location: {
      pathname: '/expo/retail',
      hash: '#grant=0e68f8e0-c464-4c10-8b4f-e4e45200f90c&return=https%3A%2F%2Fevil.example%2Fretail',
    },
    history: { state: null, replaceState() {} },
    storage,
  })
  assert.equal(sessionModule.getRetailTryOnReturnUrl(storage), 'https://leshine-wig-platform.pages.dev/retail')
})

test('retail route is public while the original kiosk route still requires expo write', () => {
  const source = fs.readFileSync(path.join(root, 'src/router/index.js'), 'utf8')
  assert.match(source, /path: '\/expo\/retail'[\s\S]*?public: true/)
  assert.match(source, /path: '\/expo\/kiosk'[\s\S]*?permission: 'expo:write'/)
})

test('retail API uses an isolated prefix and the kiosk keeps the original prefix', () => {
  const source = fs.readFileSync(path.join(root, 'src/api/clients.js'), 'utf8')
  assert.match(source, /isRetailTryOnPage\(\) \? '\/api\/expo\/retail' : '\/api\/expo'/)
  assert.match(source, /isRetailTryOnPage\(\) \? getRetailTryOnAuthorization\(\) : undefined/)
})
