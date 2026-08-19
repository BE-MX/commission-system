import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/views/expo/ExpoKiosk.vue', import.meta.url),
  'utf8',
)
const authSource = readFileSync(
  new URL('../src/stores/auth.js', import.meta.url),
  'utf8',
)

test('attract screen exposes the kiosk logout action', () => {
  assert.match(
    source,
    /<button\s+v-if="flow\.step\.value === 'attract'"\s+class="xk-nav"\s+@click="requestLogout"\s*>\s*退出登录\s*<\/button>/,
  )
})

test('logout confirmation uses the auth store and stays open while logout is pending', () => {
  assert.match(source, /import \{ useAuthStore \} from '@\/stores\/auth'/)
  assert.match(source, /const authStore = useAuthStore\(\)/)
  assert.match(source, /const logoutPending = ref\(false\)/)
  assert.match(source, /<div v-if="logoutConfirm" class="xk-confirm"/)
  assert.match(source, /@click\.self="cancelLogout"/)
  assert.match(source, /role="dialog"\s+aria-modal="true"\s+aria-labelledby="logout-confirm-title"/)
  assert.match(source, /id="logout-confirm-title"[^>]*>确认退出登录？/)
  assert.match(source, /确认退出登录？/)
  assert.match(source, /退出后需要重新输入展会设备账号才能继续使用/)
  assert.match(source, /:disabled="logoutPending"\s+@click="cancelLogout"[^>]*>\s*取消\s*<\/button>/)
  assert.match(source, /:disabled="logoutPending"\s+@click="confirmLogout"[^>]*>\s*退出登录\s*<\/button>/)
  assert.equal((source.match(/:disabled="logoutPending"/g) || []).length, 2)
  assert.match(source, /function requestLogout\(\)\s*\{[\s\S]*?logoutConfirm\.value = true[\s\S]*?flow\.touch\(\)/)
  assert.match(source, /function cancelLogout\(\)\s*\{[\s\S]*?if \(logoutPending\.value\) return[\s\S]*?logoutConfirm\.value = false[\s\S]*?\}/)

  const confirmBlock = source.match(/async function confirmLogout\(\)[\s\S]*?\n\}/)?.[0]
  assert.ok(confirmBlock, 'confirmLogout handler should be present')
  assert.match(confirmBlock, /if \(logoutPending\.value\) return/)
  assert.match(confirmBlock, /logoutPending\.value = true/)
  assert.match(confirmBlock, /await authStore\.logout\(\{\s*name: 'Login',\s*query: \{\s*redirect: '\/expo\/kiosk'\s*\},?\s*\}\)/)
  assert.match(confirmBlock, /finally\s*\{[\s\S]*?logoutPending\.value = false[\s\S]*?\}/)
  assert.doesNotMatch(confirmBlock, /logoutConfirm\.value = false/)
})

test('auth store logout keeps the default login target and awaits navigation', () => {
  assert.match(authSource, /async function logout\(target = '\/login'\)/)
  assert.match(authSource, /await router\.push\(target\)\s*\}/)
})

test('logout confirmation reuses xconfirm motion without transition all', () => {
  assert.ok(
    (source.match(/<Transition name="xconfirm">/g) || []).length >= 2,
    'logout confirmation must reuse the existing xconfirm transition',
  )
  assert.doesNotMatch(source, /transition\s*:\s*all\b/)
})
