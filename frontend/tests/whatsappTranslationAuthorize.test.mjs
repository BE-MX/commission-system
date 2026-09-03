import assert from 'node:assert/strict'
import test from 'node:test'

import {
  captureDeviceCode,
  cleanAuthorizeUrl,
  clearDeviceCode,
  pairingDecisionState,
  pairingInspectionState,
  readDeviceCode,
  waitForAuthorizeUser,
} from '../src/views/system/whatsappTranslationAuthorize.js'

test('设备码只从 fragment 读取并立即清理地址栏', () => {
  const location = { hash: '#device_code=secret-code', pathname: '/whatsapp-translation/authorize', search: '' }
  assert.equal(readDeviceCode(location), 'secret-code')
  assert.equal(cleanAuthorizeUrl(location), '/whatsapp-translation/authorize')
})

test('query string 中的设备码永远不接受', () => {
  assert.equal(readDeviceCode({ hash: '', search: '?device_code=leak' }), '')
})

test('capture writes the approved session key and clears the URL before auth work', () => {
  const calls = []
  const storage = {
    getItem: key => calls.push(['read', key]) && null,
    setItem: (key, value) => calls.push(['write', key, value]),
    removeItem: key => calls.push(['remove', key]),
  }
  const history = { replaceState: (...args) => calls.push(['url', ...args]) }
  const code = captureDeviceCode(
    { hash: '#device_code=secret-code', pathname: '/whatsapp-translation/authorize', search: '' },
    history,
    storage,
  )

  assert.equal(code, 'secret-code')
  assert.deepEqual(calls[0], ['write', 'ark_whatsapp_translation_device_code', 'secret-code'])
  assert.deepEqual(calls[1][0], 'url')
  assert.equal(calls[1].at(-1), '/whatsapp-translation/authorize')
})

test('clear removes the only authorized session key', () => {
  const removed = []
  clearDeviceCode({ removeItem: key => removed.push(key) })
  assert.deepEqual(removed, ['ark_whatsapp_translation_device_code'])
})

test('authorization waits for restored login state before redirecting', async () => {
  const calls = []
  const auth = {
    accessToken: 'token',
    initPromise: Promise.resolve(),
    user: null,
    fetchMe() {
      calls.push('me')
      this.user = { id: 1 }
    },
  }
  const router = { replace: () => calls.push('redirect') }

  const user = await waitForAuthorizeUser(auth, router)

  assert.deepEqual(calls, ['me'])
  assert.deepEqual(user, { id: 1 })
})

test('authorization redirects only after login state is unavailable', async () => {
  const calls = []
  const auth = { accessToken: null, initPromise: Promise.resolve(), user: null }
  const router = { replace: target => calls.push(target) }

  const user = await waitForAuthorizeUser(
    auth,
    router,
    { pathname: '/whatsapp-translation/authorize' },
  )

  assert.equal(user, null)
  assert.deepEqual(calls, ['/login?redirect=%2Fwhatsapp-translation%2Fauthorize'])
})

test('pairing success and repeat visits do not use the invalid state', () => {
  assert.equal(pairingInspectionState('pending'), 'ready')
  assert.equal(pairingInspectionState('ready'), 'completed')
  assert.equal(pairingDecisionState('approve'), 'completed')
  assert.equal(pairingDecisionState('reject'), 'rejected')
})
