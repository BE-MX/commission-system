import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const source = readFileSync(
  new URL('../src/views/expo/ExpoKiosk.vue', import.meta.url),
  'utf8',
)

test('attract screen exposes the kiosk logout action', () => {
  assert.match(
    source,
    /<button\s+v-if="flow\.step\.value === 'attract'"\s+class="xk-nav"\s+@click="requestLogout"\s*>\s*退出登录\s*<\/button>/,
  )
})

test('logout confirmation uses the auth store and clears itself before logout', () => {
  assert.match(source, /import \{ useAuthStore \} from '@\/stores\/auth'/)
  assert.match(source, /const authStore = useAuthStore\(\)/)
  assert.match(source, /<div v-if="logoutConfirm" class="xk-confirm"/)
  assert.match(source, /role="dialog"\s+aria-modal="true"\s+aria-labelledby="logout-confirm-title"/)
  assert.match(source, /id="logout-confirm-title"[^>]*>确认退出登录？/)
  assert.match(source, /确认退出登录？/)
  assert.match(source, /退出后需要重新输入展会设备账号才能继续使用/)
  assert.match(source, /@click="logoutConfirm = false"[^>]*>\s*取消\s*<\/button>/)
  assert.match(source, /@click="confirmLogout"[^>]*>\s*退出登录\s*<\/button>/)
  assert.match(source, /function requestLogout\(\)\s*\{[\s\S]*?logoutConfirm\.value = true[\s\S]*?flow\.touch\(\)/)
  assert.match(source, /async function confirmLogout\(\)\s*\{[\s\S]*?logoutConfirm\.value = false[\s\S]*?await authStore\.logout\(\)/)
})

test('logout confirmation reuses xconfirm motion without transition all', () => {
  assert.ok(
    (source.match(/<Transition name="xconfirm">/g) || []).length >= 2,
    'logout confirmation must reuse the existing xconfirm transition',
  )
  assert.doesNotMatch(source, /transition\s*:\s*all\b/)
})
