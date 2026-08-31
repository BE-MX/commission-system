import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const read = relative => readFileSync(new URL(relative, import.meta.url), 'utf8')

const routerSource = read('../src/router/index.js')
const requestSource = read('../src/api/request.js')
const expoApiSource = read('../src/api/expo.js')
const loginSource = read('../src/views/auth/LoginPage.vue')
const activitySource = read('../../tablet-kiosk/app/src/main/java/com/leshine/expokiosk/MainActivity.kt')

test('kiosk mode is enforced before every ordinary Ark route decision', () => {
  const boundary = routerSource.indexOf('guardExpoKioskBoundary(to)')
  const publicRoute = routerSource.indexOf('bypassCustomerImageRoute(to')
  assert.ok(boundary >= 0, 'router must enforce a persistent kiosk boundary')
  assert.ok(boundary < publicRoute, 'kiosk boundary must run before public/admin routing')
})

test('kiosk API authentication failures cannot use the shared Ark login redirect', () => {
  assert.match(requestSource, /error\.config\?\.redirectOnUnauthorized/)
  const kioskConfig = expoApiSource.match(/const KIOSK = \{[\s\S]*?\n\}/)?.[0] || ''
  assert.match(kioskConfig, /redirectOnUnauthorized:\s*false/)
})

test('kiosk login never falls through to the Ark home page', () => {
  assert.match(loginSource, /redirect === EXPO_KIOSK_PATH/)
  assert.match(loginSource, /当前账号没有展会试戴权限，请更换展会设备账号/)
})

test('the Android APP rejects main-frame navigation outside kiosk and its bounded login', () => {
  assert.match(activitySource, /override fun shouldOverrideUrlLoading/)
  assert.match(activitySource, /KioskNavigationPolicy\.shouldBlockSubframe\(request\?\.isForMainFrame\)/)
  assert.match(activitySource, /override fun doUpdateVisitedHistory/)
  assert.match(activitySource, /KioskNavigationPolicy\.decide/)
})
