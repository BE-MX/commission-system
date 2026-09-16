const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const path = require('node:path')
const vm = require('node:vm')
const sc = require('../utils/shipping-check')

function harness() {
  let page, videoMethods
  const calls = { choose: [], uploads: [], requests: [], previews: [], compress: [], info: [] }
  const context = vm.createContext({
    module: { exports: {} },
    getApp: () => ({ globalData: { baseUrl: 'https://example.test', token: 'test' }, logout() {} }),
    require: name => name.includes('shipping-video') ? videoMethods : name.includes('navigation') ? { guard: () => true } : sc,
    Page: value => { page = value },
    setTimeout() {},
    wx: {
      compressVideo: args => calls.compress.push(args), getFileInfo: args => calls.info.push(args),
      chooseMedia: args => calls.choose.push(args), uploadFile: args => calls.uploads.push(args),
      request: args => calls.requests.push(args), previewMedia: args => calls.previews.push(args),
      showModal: args => args.success({ confirm: true }), showLoading() {}, hideLoading() {},
    },
  })
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../utils/shipping-video.js'), 'utf8'), context)
  videoMethods = context.module.exports
  vm.runInContext(fs.readFileSync(path.join(__dirname, '../pages/shipping/check/check.js'), 'utf8'), context)
  page.setData = changes => Object.entries(changes).forEach(([key, value]) => {
    const parts = key.replace(/\[(\d+)\]/g, '.$1').split('.')
    let target = page.data
    for (const part of parts.slice(0, -1)) target = target[part]
    target[parts.at(-1)] = value
  })
  page._loadByQr('ARK-I:OB001:test')
  calls.requests.pop().success({ statusCode: 200, data: {
    record: { outbound_record_id: 'OB001' }, items: [{ item_id: 'IT1', model: 'Weft' }],
    inspection: { status: 'draft', edit_version: 2, remark: '已有备注' }, photos: [], videos: [],
  } })
  return { page, calls }
}

test('video captures then compresses before uploading with the frozen item and version', () => {
  const { page, calls } = harness()
  page.onItemVideoTap({ currentTarget: { dataset: { itemId: 'IT1' } } })
  assert.deepEqual(Array.from(calls.choose[0].sourceType), ['camera'])
  assert.deepEqual(Array.from(calls.choose[0].mediaType), ['video'])
  calls.choose[0].success({ tempFiles: [{ tempFilePath: '/album/clip.mp4', size: 3000 }] })
  assert.equal(calls.uploads.length, 0)
  assert.equal(page.data.uploading, true)
  assert.equal(calls.compress[0].quality, 'medium')
  calls.compress[0].success({ tempFilePath: '/compressed.mp4' })
  calls.info[0].success({ size: 2000 })
  const upload = calls.uploads[0]
  assert.equal(upload.filePath, '/compressed.mp4')
  assert.ok(upload.url.endsWith('/videos'))
  assert.equal(upload.formData.item_id, 'IT1')
  assert.equal(upload.formData.edit_version, '2')
  assert.equal(upload.timeout, 300000)
  assert.equal(page.data.uploading, true)
  page.onSubmitTap()
  assert.equal(calls.requests.length, 0)
  upload.success({ statusCode: 200, data: JSON.stringify({ id: 19, file_path: 'aa/clip.mp4' }) })
  assert.equal(page.data.items[0].videos[0].id, 19)
  assert.equal(page.data.totalPhotos, 0)
  assert.equal(page.data.canSubmit, false)
  page.onPreviewVideo({ currentTarget: { dataset: { videoId: 19 } } })
  assert.equal(calls.previews[0].sources[0].type, 'video')
})

test('oversized videos and submitted pages cannot start uploads', () => {
  const { page, calls } = harness()
  page.onWholeVideoTap()
  calls.choose[0].success({ tempFiles: [{ tempFilePath: '/clip.mp4', size: 101 * 1024 * 1024 }] })
  calls.compress[0].success({ tempFilePath: '/large.mp4' })
  calls.info[0].success({ size: 101 * 1024 * 1024 })
  assert.equal(calls.uploads.length, 0)
  assert.equal(page.data.errorTitle, '视频过大')
  page.data.submitted = true
  page.onWholeVideoTap()
  assert.equal(calls.choose.length, 1)
})

test('refresh restores a recalled version and remark; submit sends that version', () => {
  const { page, calls } = harness()
  assert.equal(page.data.remark, '已有备注')
  page.onRefreshInspection()
  assert.equal(calls.requests[0].data.qr_raw, 'ARK-I:OB001:test')
  calls.requests[0].success({ statusCode: 200, data: { record: { outbound_record_id: 'OB001' }, inspection: { status: 'draft', edit_version: 3 } } })
  page.onSubmitTap()
  assert.equal(calls.requests.at(-1).data.edit_version, 3)
})

test('video delete handles a proxy HTML error and unlocks the page', () => {
  const { page, calls } = harness()
  page.onDeleteVideo({ currentTarget: { dataset: { videoId: 19 } } })
  const request = calls.requests[0]
  assert.ok(request.url.endsWith('/videos/19?edit_version=2'))
  request.success({ statusCode: 502, data: '<html>Bad gateway</html>' })
  request.complete()
  assert.equal(page.data.errorTitle, '删除失败')
  assert.equal(page.data.uploading, false)
})

test('video groups are separate from photo counts and submit gating', () => {
  const view = sc.decorateView({ record: {}, items: [{ item_id: 1 }], videos: [
    { id: 1, item_id: null, file_path: 'a.mp4' }, { id: 2, item_id: 1, file_path: 'b.mov' },
  ] })
  assert.equal(view.wholeVideos.length, 1)
  assert.equal(view.items[0].videos.length, 1)
  assert.equal(view.totalPhotos, 0)
  assert.equal(view.canSubmit, false)
})


test('album remains available, cancellation and compression failure release lock', () => {
  const { page, calls } = harness()
  page.onWholeAlbumVideoTap()
  assert.deepEqual(Array.from(calls.choose[0].sourceType), ['album'])
  calls.choose[0].fail({ errMsg: 'cancel' })
  assert.equal(page.data.uploading, false)
  page.onWholeVideoTap()
  calls.choose[1].success({ tempFiles: [{ tempFilePath: '/capture.mp4', size: 200000000 }] })
  calls.compress[0].fail({})
  assert.equal(page.data.uploading, false)
  assert.equal(calls.uploads.length, 0)
  assert.equal(page.data.errorTitle, '视频压缩失败')
})

test('stale compression callback does not upload to another record', () => {
  const { page, calls } = harness()
  page.onWholeVideoTap()
  calls.choose[0].success({ tempFiles: [{ tempFilePath: '/capture.mp4', size: 3000 }] })
  page.onUnload()
  calls.compress[0].success({ tempFilePath: '/compressed.mp4' })
  assert.equal(calls.uploads.length, 0)
  assert.equal(calls.info.length, 0)
})
