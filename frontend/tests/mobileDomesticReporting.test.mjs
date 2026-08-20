import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import {
  buildMobileReportPayload,
  collectRequirementImagePaths,
  isDefinitiveSubmitFailure,
  isReportingAuthError,
  parseDomesticReportingCode,
  reportingPendingStorageKey,
} from '../src/views/domestic/reporting/reportingState.js'

test('识别内贸批量码和逐件码，并清理扫码头尾字符', () => {
  assert.deepEqual(parseDomesticReportingCode('\0 ARK-D:42:Ab12cd34\n'), {
    type: 'item', id: 42, sign: 'ab12cd34', raw: 'ARK-D:42:Ab12cd34',
  })
  assert.deepEqual(parseDomesticReportingCode('ARK-DU:77:ffeedd11'), {
    type: 'unit', id: 77, sign: 'ffeedd11', raw: 'ARK-DU:77:ffeedd11',
  })
})

test('拒绝外贸码、非数字 ID 和超出安全整数范围的二维码', () => {
  assert.equal(parseDomesticReportingCode('ARK-P:42:ab12cd34'), null)
  assert.equal(parseDomesticReportingCode('ARK-D:x:ab12cd34'), null)
  assert.equal(parseDomesticReportingCode('ARK-D:42:abcd'), null)
  assert.equal(parseDomesticReportingCode('ARK-D:9007199254740992:ab12cd34'), null)
})

test('批量与逐件报工负载严格复用后端字段', () => {
  const quantityScan = { item_id: 9, report_mode: 'quantity', next_step: { progress_id: 12 } }
  assert.deepEqual(buildMobileReportPayload(quantityScan, { sign: 'ignored' }, 5, 'req-q'), {
    item_id: 9, progress_id: 12, qty: 5, request_id: 'req-q',
  })

  const unitScan = { item_id: 9, unit_id: 31, report_mode: 'unit', next_step: { progress_id: 12 } }
  assert.deepEqual(buildMobileReportPayload(unitScan, { sign: 'ab12cd34' }, 1, 'req-u'), {
    item_id: 9, progress_id: 12, qty: 1, request_id: 'req-u', unit_id: 31, unit_sign: 'ab12cd34',
  })
})

test('只有明确的非鉴权 4xx 会清除本地待确认提交', () => {
  const error = status => ({ response: { status } })
  assert.equal(isDefinitiveSubmitFailure(error(422)), true)
  assert.equal(isDefinitiveSubmitFailure(error(401)), false)
  const fastApiAuth = { response: { status: 403, data: { detail: 'Not authenticated' } } }
  assert.equal(isReportingAuthError(fastApiAuth), true)
  assert.equal(isDefinitiveSubmitFailure(fastApiAuth), false)
  assert.equal(isDefinitiveSubmitFailure(error(500)), false)
  assert.equal(isDefinitiveSubmitFailure(new Error('offline')), false)
})

test('待确认幂等请求按账号隔离，避免共享 PDA 串单或锁死', () => {
  assert.equal(reportingPendingStorageKey(12), 'ark_mobile_domestic_pending_v1:12')
  assert.notEqual(reportingPendingStorageKey(12), reportingPendingStorageKey(13))
})

test('汇总四类参考图并忽略空路径', () => {
  assert.deepEqual(collectRequirementImagePaths({
    hairstyle_images: ['hair/a.jpg', ''],
    color_images: ['color/b.jpg'],
    style_images: null,
    remark_images: ['remark/c.jpg'],
  }), ['hair/a.jpg', 'color/b.jpg', 'remark/c.jpg'])
})

test('扫码页是需登录的全屏路由，手机登录后会恢复深链', async () => {
  const routerSource = await readFile(new URL('../src/router/index.js', import.meta.url), 'utf8')
  const loginSource = await readFile(new URL('../src/views/auth/LoginPage.vue', import.meta.url), 'utf8')

  assert.match(routerSource, /path: '\/domestic\/reporting'[\s\S]*MobileDomesticReporting\.vue'[\s\S]*meta: \{ title: '内贸扫码报工' \}/)
  assert.doesNotMatch(routerSource, /meta: \{ title: '内贸扫码报工', public: true \}/)
  assert.match(routerSource, /redirectTarget\.startsWith\('\/domestic\/reporting'\)/)
  assert.match(loginSource, /redirect\.startsWith\('\/domestic\/reporting'\)/)
})

test('未知提交结果会锁住新幂等号，只允许沿用原请求重试', async () => {
  const stateSource = await readFile(new URL('../src/views/domestic/reporting/composables/useMobileDomesticReporting.js', import.meta.url), 'utf8')
  const confirmSource = await readFile(new URL('../src/views/domestic/reporting/MobileReportConfirm.vue', import.meta.url), 'utf8')

  assert.match(stateSource, /pending\.value && pending\.value\.requestId !== requestId/)
  assert.match(stateSource, /busy\.value \|\| pending\.value\) return/)
  assert.match(confirmSource, /:disabled="submitting \|\| blocked"/)
})

test('生产构建包含 Android 6 和 Chrome 49 的旧浏览器兼容包', async () => {
  const viteSource = await readFile(new URL('../vite.config.js', import.meta.url), 'utf8')
  assert.match(viteSource, /legacy\(\{[\s\S]*Android >= 6[\s\S]*Chrome >= 49/)
})
