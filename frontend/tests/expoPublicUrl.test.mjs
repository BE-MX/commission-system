import test from 'node:test'
import assert from 'node:assert/strict'

import { publicOrigin } from '../src/views/expo/kiosk/publicUrl.js'

function withLocation(hostname, port, origin, fn) {
  globalThis.location = { hostname, port, origin }
  try { fn() } finally { delete globalThis.location }
}

test('裸 IP 且无显式端口 → 降到 http（客户手机不认自签证书）', () => {
  withLocation('154.8.205.162', '', 'https://154.8.205.162', () => {
    assert.equal(publicOrigin(), 'http://154.8.205.162')
  })
})

test('备案域名 → 保持原 origin，不降级', () => {
  withLocation('leshine.work', '', 'https://leshine.work', () => {
    assert.equal(publicOrigin(), 'https://leshine.work')
  })
})

test('裸 IP 带显式端口 → 原样不猜（无从推断对应的 http 端口）', () => {
  withLocation('192.168.101.193', '8001', 'http://192.168.101.193:8001', () => {
    assert.equal(publicOrigin(), 'http://192.168.101.193:8001')
  })
})
