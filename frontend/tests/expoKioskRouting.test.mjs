import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  EXPO_KIOSK_LOCK_KEY,
  EXPO_KIOSK_PATH,
  expoKioskLoginLocation,
  guardExpoKioskBoundary,
  isExpoKioskMode,
  isExpoKioskTarget,
} from '../src/router/expoKioskRoute.js'
import {
  readSessionItem,
  removeSessionItem,
  writeSessionItem,
} from '../src/utils/safeSessionStorage.js'

class MemoryStorage {
  values = new Map()
  getItem(key) { return this.values.get(key) ?? null }
  setItem(key, value) { this.values.set(key, String(value)) }
}

const routerSource = readFileSync(
  new URL('../src/router/index.js', import.meta.url),
  'utf8',
)
const expoApiSource = readFileSync(
  new URL('../src/api/expo.js', import.meta.url),
  'utf8',
)
const loginSource = readFileSync(
  new URL('../src/views/auth/LoginPage.vue', import.meta.url),
  'utf8',
)

test('entering kiosk locks the tab and never redirects a backend route through', () => {
  const storage = new MemoryStorage()
  assert.equal(guardExpoKioskBoundary({ path: '/dashboard' }, storage), null)
  assert.equal(guardExpoKioskBoundary({ path: EXPO_KIOSK_PATH }, storage), null)
  assert.equal(storage.getItem(EXPO_KIOSK_LOCK_KEY), '1')
  assert.equal(isExpoKioskMode(storage), true)
  assert.deepEqual(
    guardExpoKioskBoundary({ path: '/dashboard' }, storage),
    { name: 'ExpoKiosk', replace: true },
  )
  assert.deepEqual(
    guardExpoKioskBoundary({ path: '/create/invite-token' }, storage),
    { name: 'ExpoKiosk', replace: true },
  )
})

test('route aliases with trailing slashes or case differences still enter kiosk mode', () => {
  for (const route of [
    { name: 'ExpoKiosk', path: '/expo/kiosk/' },
    { name: 'ExpoKiosk', path: '/EXPO/KIOSK' },
    { path: '/expo/kiosk/' },
    { path: '/EXPO/KIOSK' },
  ]) {
    const storage = new MemoryStorage()
    assert.equal(isExpoKioskTarget(route), true)
    assert.equal(guardExpoKioskBoundary(route, storage), null)
    assert.equal(storage.getItem(EXPO_KIOSK_LOCK_KEY), '1')
    assert.deepEqual(
      guardExpoKioskBoundary({ path: '/dashboard' }, storage),
      { name: 'ExpoKiosk', replace: true },
    )
  }
})

test('disabled session storage cannot break kiosk routing login or logout helpers', () => {
  const blocked = {
    getItem() { throw new Error('blocked') },
    setItem() { throw new Error('blocked') },
    removeItem() { throw new Error('blocked') },
  }
  assert.equal(readSessionItem('x', blocked), null)
  assert.doesNotThrow(() => writeSessionItem('x', '1', blocked))
  assert.doesNotThrow(() => removeSessionItem('x', blocked))
  assert.equal(
    guardExpoKioskBoundary({ name: 'ExpoKiosk', path: '/expo/kiosk' }, blocked),
    null,
  )
  assert.deepEqual(
    guardExpoKioskBoundary({ path: '/dashboard' }, blocked),
    { name: 'ExpoKiosk', replace: true },
  )
})

test('a locked kiosk tab may open login only when it returns to kiosk', () => {
  const storage = new MemoryStorage()
  guardExpoKioskBoundary({ path: EXPO_KIOSK_PATH }, storage)

  assert.deepEqual(
    guardExpoKioskBoundary({ path: '/login', query: { reason: 'expired' } }, storage),
    expoKioskLoginLocation({ reason: 'expired' }),
  )
  assert.equal(
    guardExpoKioskBoundary({
      path: '/login',
      query: { redirect: EXPO_KIOSK_PATH },
    }, storage),
    null,
  )
})

test('router applies kiosk isolation before public and mobile routing and never permission-falls back to dashboard', () => {
  const boundary = routerSource.indexOf('const kioskBoundary = guardExpoKioskBoundary(to)')
  const publicBypass = routerSource.indexOf('if (bypassCustomerImageRoute(')
  const mobileRouting = routerSource.indexOf('const isMobileUA')
  assert.ok(boundary >= 0 && boundary < publicBypass)
  assert.ok(boundary < mobileRouting)
  assert.match(
    routerSource,
    /if \(isExpoKioskTarget\(to\)\)[\s\S]*?expoKioskLoginLocation\(\{ reason: 'permission' \}\)/,
  )
  assert.match(loginSource, /redirect === EXPO_KIOSK_PATH && !authStore\.hasPermission\('expo:write'\)/)
  assert.match(loginSource, /当前账号没有展会试戴权限，请更换展会设备账号/)
})

test('every kiosk API request disables the shared unauthorized redirect', () => {
  const kioskConfig = expoApiSource.match(/const KIOSK = \{[\s\S]*?\n\}/)?.[0] || ''
  assert.match(kioskConfig, /redirectOnUnauthorized:\s*false/)
  for (const name of [
    'registerCustomer', 'updateCustomer', 'getKioskLeads', 'getKioskStrategy',
    'createUploadTicket', 'getPendingPhoto', 'createSession', 'getSession',
    'contactExpoAdmin', 'generateResults', 'getWigPicker', 'getWigColors',
    'setReaction', 'submitFeedback',
  ]) {
    const start = expoApiSource.indexOf(`export function ${name}`)
    const end = expoApiSource.indexOf('\n}', start)
    assert.ok(start >= 0, `${name} missing`)
    assert.match(expoApiSource.slice(start, end + 2), /\.\.\.KIOSK/, `${name} may redirect`)
  }
})
