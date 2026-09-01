const test = require('node:test')
const assert = require('node:assert/strict')

const sc = require('../utils/shipping-check')

// ─── classifyScan ──────────────────────────────

test('classifyScan treats ARK-I: as shipping QR and keeps the raw payload unparsed', function () {
  assert.deepEqual(sc.classifyScan('ARK-I:42:9f3ab'), { kind: 'shipping', raw: 'ARK-I:42:9f3ab' })
  // 签名格式后端定，小程序不校验——畸形段也照样原文上交
  assert.deepEqual(sc.classifyScan('  ARK-I:anything-goes  '), { kind: 'shipping', raw: 'ARK-I:anything-goes' })
})

test('classifyScan flags domestic codes so the page can tell the worker to switch', function () {
  assert.equal(sc.classifyScan('ARK-D:7:abc').kind, 'domestic')
  assert.equal(sc.classifyScan('ARK-DU:7:abc').kind, 'domestic')
})

test('classifyScan rejects empty and foreign codes', function () {
  assert.equal(sc.classifyScan('').kind, 'empty')
  assert.equal(sc.classifyScan('   ').kind, 'empty')
  assert.equal(sc.classifyScan(null).kind, 'empty')
  assert.equal(sc.classifyScan(undefined).kind, 'empty')
  assert.equal(sc.classifyScan('ARK-P:9:abc').kind, 'other')
  assert.equal(sc.classifyScan('https://example.com/x').kind, 'other')
})

// ─── imageUrl ──────────────────────────────

test('imageUrl keeps path slashes intact and encodes special characters', function () {
  assert.equal(
    sc.imageUrl('https://leshine.work', 'shipping/2026/a b.jpg'),
    'https://leshine.work/api/mini/shipping-inspection/images/shipping/2026/a%20b.jpg'
  )
})

// ─── photoStats ──────────────────────────────

test('photoStats sums whole-order and per-item photos and gates submit on at least one', function () {
  var items = [{ photos: [{ id: 2 }, { id: 3 }] }, { photos: [] }]
  assert.deepEqual(sc.photoStats(items, [{ id: 1 }], false), { totalPhotos: 3, canSubmit: true })
  assert.deepEqual(sc.photoStats([], [], false), { totalPhotos: 0, canSubmit: false })
})

test('photoStats blocks submit after the inspection was submitted', function () {
  var items = [{ photos: [{ id: 2 }] }]
  assert.deepEqual(sc.photoStats(items, [{ id: 1 }], true), { totalPhotos: 2, canSubmit: false })
})

// ─── decorateView ──────────────────────────────

const payload = {
  record: {
    outbound_record_id: 9,
    outbound_no: 'CK20260901-01',
    outbound_date: '2026-09-01',
    customer_name: '杭州某客户'
  },
  items: [
    { item_id: 11, product_name: '蕾丝假发', qty: 20, unit: '件', spec: '13x4', sku: 'LS-01' },
    { item_id: 12, product_name: '发条', qty: 5, unit: '套', spec: '', sku: '' }
  ],
  inspection: null,
  photos: [
    { id: 101, item_id: null, file_path: 'shipping/9/whole.jpg' },
    { id: 102, item_id: 11, file_path: 'shipping/9/a.jpg' },
    { id: 103, item_id: 11, file_path: 'shipping/9/b.jpg' }
  ]
}

test('decorateView groups photos under whole-order and matching item rows', function () {
  var view = sc.decorateView(payload)
  assert.equal(view.record.outbound_no, 'CK20260901-01')
  assert.equal(view.wholePhotos.length, 1)
  assert.equal(view.wholePhotos[0].filePath, 'shipping/9/whole.jpg')
  assert.equal(view.items[0].photos.length, 2)
  assert.equal(view.items[0].photoCount, 2)
  assert.equal(view.items[1].photoCount, 0)
  assert.equal(view.totalPhotos, 3)
  assert.equal(view.canSubmit, true)
  assert.equal(view.submitted, false)
  assert.equal(view.statusText, '待检验')
})

test('decorateView pre-computes row display text so wxml stays expression-free', function () {
  var view = sc.decorateView(payload)
  assert.equal(view.items[0].qtyText, '20件')
  assert.equal(view.items[0].specText, '13x4 · LS-01')
  assert.equal(view.items[1].qtyText, '5套')
  assert.equal(view.items[1].specText, '')
})

test('decorateView marks a submitted inspection read-only', function () {
  var done = sc.decorateView({
    record: payload.record,
    items: payload.items,
    inspection: { status: 'submitted', photo_count: 1 },
    photos: [{ id: 101, item_id: null, file_path: 'shipping/9/whole.jpg' }]
  })
  assert.equal(done.submitted, true)
  assert.equal(done.statusText, '已提交')
  assert.equal(done.canSubmit, false)
  assert.equal(done.totalPhotos, 1)
})

test('decorateView tolerates an empty payload', function () {
  var view = sc.decorateView({})
  assert.deepEqual(view.record, {
    outbound_record_id: undefined,
    outbound_no: '',
    outbound_date: '',
    customer_name: ''
  })
  assert.deepEqual(view.items, [])
  assert.deepEqual(view.wholePhotos, [])
  assert.equal(view.canSubmit, false)
  assert.equal(view.submitted, false)
})

test('decorateView drops orphan photos whose item_id matches no detail row', function () {
  var view = sc.decorateView({
    record: payload.record,
    items: [payload.items[0]],
    inspection: null,
    photos: [{ id: 109, item_id: 999, file_path: 'shipping/9/orphan.jpg' }]
  })
  assert.equal(view.items[0].photoCount, 0)
  assert.equal(view.totalPhotos, 0)
  assert.equal(view.canSubmit, false)
})

// ─── buildSubmitBody ──────────────────────────────

test('buildSubmitBody assembles the submit payload with a default empty remark', function () {
  assert.deepEqual(sc.buildSubmitBody(9, 'req-1', undefined), {
    outbound_record_id: 9,
    request_id: 'req-1',
    remark: ''
  })
  assert.deepEqual(sc.buildSubmitBody(9, 'req-2', '外箱破损'), {
    outbound_record_id: 9,
    request_id: 'req-2',
    remark: '外箱破损'
  })
})

test('buildSubmitBody requires record id and request id', function () {
  assert.throws(function () { sc.buildSubmitBody(null, 'req-1', '') })
  assert.throws(function () { sc.buildSubmitBody(9, '', '') })
})
