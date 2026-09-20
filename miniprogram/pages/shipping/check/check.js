// pages/shipping/check/check.js — 发货检验
// 扫出库单二维码（ARK-I: 原文直交后端验签，小程序不解析格式）→ 整单/明细拍照 → 提交。
// 零 import 纯回调，状态机 idle→loading→ready→submitting，与其余页面同一套风格。
var app = getApp()
var navigation = require('../../../utils/navigation')
var sc = require('../../../utils/shipping-check')
var videoMethods = require('../../../utils/shipping-video')

Page(Object.assign({
  onShow: function () {
    if (!navigation.guard('shipping')) return
    this.setData({ scanActive: true })
    if (this.data.submitted && !this.data.uploading && !this.data.pendingMedia && this._qrRaw) this._loadByQr(this._qrRaw, true)
  },
  onHide: function () { this.setData({ scanActive: false }) },
  onPreviewScanExample: function () {
    wx.getImageInfo({
      src: '/assets/shipping-scan-example.png',
      success: function (image) { wx.previewImage({ current: image.path, urls: [image.path] }) },
      fail: function () { wx.showToast({ title: '示例图片加载失败', icon: 'none' }) }
    })
  },
  data: {
    scanActive: false,
    statusBarHeight: 20,
    state: 'idle',            // idle | loading | ready | submitting
    record: null,             // 出库单头：单号/客户/日期
    items: [],                // 明细行（含每行照片）
    wholePhotos: [],          // 整单照片
    wholeVideos: [],
    editVersion: 0,
    totalPhotos: 0,
    canSubmit: false,
    submitted: false,         // 已提交：整页只读
    statusText: '',
    remark: '',
    mediaStage: '',
    mediaProgress: 0,
    pendingMedia: false,
    mediaError: '',
    mediaItemId: null,
    uploading: false,         // 有照片在传时挡住提交/再拍，避免顺序错乱
    successVisible: false,
    successTitle: '',
    successDesc: '',
    errorVisible: false,
    errorTitle: '',
    errorMessage: ''
  },

  _requestId: '',
  onUnload: function () { this._imageBatch += 1; wx.hideLoading() },

  _imageBatch: 0,
  _qrRaw: '',
  onRefreshInspection: function () {
    if (this._qrRaw && !this.data.uploading && !this.data.pendingMedia && this.data.state === 'ready') this._loadByQr(this._qrRaw, true)
  },

  onLoad: function () {
    if (!navigation.guard('shipping')) return
    var info = wx.getSystemInfoSync()
    this.setData({ statusBarHeight: info.statusBarHeight || 20 })
  },

  _header: function () {
    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) header['Authorization'] = 'Bearer ' + app.globalData.token
    return header
  },

  // ─── 扫码 ──────────────────────────────

  onScanTap: function () {
    if (this.data.state !== 'idle') return
    var self = this
    wx.scanCode({
      scanType: ['qrCode'],
      success: function (scan) {
        var r = sc.classifyScan(scan.result)
        if (r.kind === 'empty') {
          wx.showToast({ title: '未扫到内容', icon: 'none' })
          return
        }
        if (r.kind === 'domestic') {
          wx.showToast({ title: '请扫出库单二维码', icon: 'none', duration: 2000 })
          return
        }
        if (r.kind !== 'shipping') {
          wx.showToast({ title: '二维码无效，请扫出库单二维码', icon: 'none', duration: 2000 })
          return
        }
        self._loadByQr(r.raw)     // 原文直交后端验签
      }
    })
  },

  _loadByQr: function (raw, refresh) {
    var self = this
    this.setData({ state: 'loading' })
    this._qrRaw = raw
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/shipping-inspection/' + (refresh ? 'refresh' : 'scan'),
      method: 'POST',
      header: this._header(),
      timeout: 30000,
      data: { qr_raw: raw, request_id: 'scan-' + Date.now() + '-' + Math.random().toString(36).slice(2) },
      success: function (res) {
        if (res.statusCode === 401) { self.setData({ state: 'idle' }); app.logout(); return }
        // mini 端惯例：成功返回裸业务 dict，无 code/data 信封；错误才走 detail
        if (res.statusCode >= 400) {
          var detail = (res.data && res.data.detail) || {}
          self.setData({ state: 'idle' })
          self._error('扫码失败', detail.message || '请重试')
          return
        }
        var view = sc.decorateView(res.data || {})
        self._requestId = ''
        self.setData({
          state: 'ready',
          record: view.record,
          items: view.items,
          wholePhotos: view.wholePhotos,
          wholeVideos: view.wholeVideos,
          editVersion: view.editVersion,
          totalPhotos: view.totalPhotos,
          canSubmit: view.canSubmit,
          submitted: view.submitted,
          statusText: view.statusText,
          remark: view.remark
        })
        self._loadPhotoUrls()
      },
      fail: function () {
        self.setData({ state: 'idle' })
        self._error('网络异常', '请检查网络后重试')
      }
    })
  },

  // 图片端点要 Bearer 鉴权，<image src> 带不了 header，
  // 跟随 pages/domestic/scan/scan.js _loadImages 的先例：downloadFile 带 header 换本地临时路径再显示。
  // 批次令牌同样不能省：连扫两单时先发起的那批后完成会覆盖，工人会对着上一单的图拍照。
  _loadPhotoUrls: function () {
    var self = this
    var batch = ++this._imageBatch
    var pending = []
    this.data.wholePhotos.forEach(function (p) { pending.push(p) })
    this.data.items.forEach(function (it) {
      it.photos.forEach(function (p) { pending.push(p) })
    })
    if (!pending.length) return
    pending.forEach(function (p) {
      wx.downloadFile({
        url: sc.imageUrl(app.globalData.baseUrl, p.filePath),
        header: self._header(),
        success: function (res) {
          if (res.statusCode === 401) { app.logout(); return }
          if (res.statusCode !== 200) return
          if (batch !== self._imageBatch) return
          self._setPhotoUrl(p.id, res.tempFilePath)
        }
      })
    })
  },

  _setPhotoUrl: function (photoId, url) {
    var obj = {}
    var i, j
    var whole = this.data.wholePhotos
    for (i = 0; i < whole.length; i++) {
      if (whole[i].id === photoId) obj['wholePhotos[' + i + '].url'] = url
    }
    var items = this.data.items
    for (i = 0; i < items.length; i++) {
      for (j = 0; j < items[i].photos.length; j++) {
        if (items[i].photos[j].id === photoId) obj['items[' + i + '].photos[' + j + '].url'] = url
      }
    }
    if (Object.keys(obj).length) this.setData(obj)
  },

  // ─── 拍照上传 ──────────────────────────────

  onWholeCameraTap: function () { this._choosePhoto(null) },

  onItemCameraTap: function (e) { this._choosePhoto(e.currentTarget.dataset.itemId) },

  onWholeAlbumPhotoTap: function () { this._choosePhoto(null, 'album') },
  onItemAlbumPhotoTap: function (e) { this._choosePhoto(e.currentTarget.dataset.itemId, 'album') },

  _choosePhoto: function (itemId, sourceType) {
    if (this.data.submitted || this.data.state !== 'ready' || this.data.uploading || this.data.pendingMedia) return
    var self = this
    var batch = this._imageBatch
    this.setData({ uploading: true })
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: [sourceType || 'camera'],
      sizeType: ['compressed'],
      success: function (res) {
        if (batch !== self._imageBatch) return
        self.setData({ uploading: false })
        if (res.tempFiles && res.tempFiles.length > 0) {
          self._upload(res.tempFiles[0].tempFilePath, itemId === undefined ? null : itemId)
        }
      },
      fail: function (err) {
        if (batch !== self._imageBatch) return
        self.setData({ uploading: false })
        if ((err.errMsg || '').indexOf('cancel') < 0) self._error('无法选择照片', '请检查相机和相册权限后重试')
      }
    })
  },

  _upload: function (filePath, itemId, mediaType, retry) {
    if (this.data.submitted || this.data.state !== 'ready' || this.data.uploading || this.data.pendingMedia) return
    var self = this
    var batch = this._imageBatch
    var intent = retry || { filePath: filePath, itemId: itemId, mediaType: mediaType,
      recordId: this.data.record.outbound_record_id, version: this.data.editVersion,
      requestId: 'media-' + Date.now() + '-' + Math.random().toString(36).slice(2) }
    this._pendingUpload = intent
    this.setData({ uploading: true, mediaStage: '上传中', mediaProgress: 0, mediaError: '', mediaItemId: itemId == null ? null : itemId })
    // multipart 的 formData 只收字符串；整单照片不传 item_id
    var formData = { outbound_record_id: String(intent.recordId), edit_version: String(intent.version), request_id: intent.requestId }
    if (itemId !== null && itemId !== undefined) formData.item_id = String(itemId)
    var task = wx.uploadFile({
      url: app.globalData.baseUrl + '/api/mini/shipping-inspection/' + (mediaType === 'video' ? 'videos' : 'photos'),
      timeout: 300000,
      filePath: filePath,
      name: 'file',
      header: { 'Authorization': 'Bearer ' + app.globalData.token },
      formData: formData,
      success: function (uploadRes) {
        if (batch !== self._imageBatch) return
        wx.hideLoading()
        self.setData({ uploading: false, mediaStage: '' })
        if (uploadRes.statusCode === 401) { self._mediaFailure('登录已过期', '请重新登录后核对上传结果'); app.logout(); return }
        var body = {}
        try { body = JSON.parse(uploadRes.data) } catch (e) {}
        // mini 端惯例：成功返回裸 dict {id, file_path}；错误走 detail.message
        if (uploadRes.statusCode >= 400) {
          var detail = body.detail || {}
          self._mediaFailure('上传失败', detail.message || '请重试')
          return
        }
        // 刚拍的本地临时路径直接用于显示，省一次回源下载
        if (!body.id || !body.file_path) { self._mediaFailure('上传未确认', '请重试上传'); return }
        self._pendingUpload = null
        self.setData({ pendingMedia: false, mediaError: '' })
        var append = mediaType === 'video' ? self._appendVideo : self._appendPhoto
        append.call(self, {
          id: body.id,
          itemId: itemId === undefined ? null : itemId,
          filePath: body.file_path,
          url: filePath
        })
      },
      fail: function () {
        if (batch !== self._imageBatch) return
        self._mediaFailure('上传失败', '网络异常，请重试上传')
      }
    })
    if (task && task.onProgressUpdate) task.onProgressUpdate(function (event) {
      if (batch === self._imageBatch && self.data.uploading) self.setData({ mediaProgress: event.progress })
    })
  },

  _appendPhoto: function (photo) {
    var obj = {}
    if (photo.itemId === null || photo.itemId === undefined) {
      obj['wholePhotos[' + this.data.wholePhotos.length + ']'] = photo
    } else {
      for (var i = 0; i < this.data.items.length; i++) {
        if (String(this.data.items[i].item_id) === String(photo.itemId)) {
          var n = this.data.items[i].photos.length
          obj['items[' + i + '].photos[' + n + ']'] = photo
          obj['items[' + i + '].photoCount'] = n + 1
          break
        }
      }
    }
    this.setData(obj)
    this._recount()
  },

  _recount: function () {
    var stats = sc.photoStats(this.data.items, this.data.wholePhotos, this.data.submitted)
    this.setData({ totalPhotos: stats.totalPhotos, canSubmit: stats.canSubmit })
  },

  // ─── 预览 / 删除 ──────────────────────────────

  onPreviewPhoto: function (e) {
    var group = e.currentTarget.dataset.group      // 'whole' 或 item_id
    var index = e.currentTarget.dataset.index
    var photos = this.data.wholePhotos
    if (group !== 'whole') {
      for (var i = 0; i < this.data.items.length; i++) {
        if (String(this.data.items[i].item_id) === String(group)) {
          photos = this.data.items[i].photos
          break
        }
      }
    }
    var urls = []
    photos.forEach(function (p) { if (p.url) urls.push(p.url) })
    if (!urls.length) return
    var current = photos[index] && photos[index].url ? photos[index].url : urls[0]
    wx.previewImage({ current: current, urls: urls })
  },

  onDeletePhoto: function (e) {
    if (this.data.submitted || this.data.state !== 'ready' || this.data.uploading || this.data.pendingMedia) return
    var photoId = e.currentTarget.dataset.photoId
    var batch = this._imageBatch
    var self = this
    wx.showModal({
      title: '删除照片',
      content: '确定删除这张照片吗？',
      confirmText: '删除',
      confirmColor: '#E53935',
      success: function (res) {
        if (res.confirm && batch === self._imageBatch) self._deletePhoto(photoId)
      }
    })
  },

  _deletePhoto: function (photoId) {
    if (this.data.submitted || this.data.state !== 'ready' || this.data.uploading || this.data.pendingMedia) return
    var batch = this._imageBatch
    this.setData({ uploading: true })
    var self = this
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/shipping-inspection/photos/' + photoId + '?edit_version=' + this.data.editVersion,
      method: 'DELETE',
      header: this._header(),
      timeout: 30000,
      success: function (res) {
        if (batch !== self._imageBatch) return
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode >= 400) {
          var detail = (res.data && res.data.detail) || {}
          self._error('删除失败', detail.message || '请重试')
          return
        }
        var whole = self.data.wholePhotos.filter(function (p) { return p.id !== photoId })
        var items = self.data.items.map(function (it) {
          var ps = it.photos.filter(function (p) { return p.id !== photoId })
          var copy = {}
          for (var k in it) copy[k] = it[k]
          copy.photos = ps
          copy.photoCount = ps.length
          return copy
        })
        self.setData({ wholePhotos: whole, items: items })
        self._recount()
      },
      fail: function () { if (batch === self._imageBatch) self._error('网络异常', '请检查网络后重试') },
      complete: function () { if (batch === self._imageBatch) self.setData({ uploading: false }) }
    })
  },

  // ─── 提交 ──────────────────────────────

  onRemarkInput: function (e) { this.setData({ remark: e.detail.value }) },

  onSubmitTap: function () {
    if (this.data.state !== 'ready' || this.data.submitted || this.data.uploading || this.data.pendingMedia) return
    var self = this
    // 幂等键在同一次提交里复用：弱网下"已提交但响应丢了"时再点一次不会报两单
    if (!this._requestId) {
      this._requestId = Date.now() + '-' + Math.random().toString(36).slice(2, 12)
    }
    var body
    try {
      body = sc.buildSubmitBody(this.data.record.outbound_record_id, this._requestId, this.data.remark, this.data.editVersion)
    } catch (err) {
      return
    }
    this.setData({ state: 'submitting' })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/shipping-inspection/submit',
      method: 'POST',
      header: this._header(),
      timeout: 30000,
      data: body,
      success: function (res) {
        self.setData({ state: 'ready' })
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode >= 400) {
          // 无照片时后端 400 兜底：detail.message「每个发货单至少上传一张照片」
          var detail = (res.data && res.data.detail) || {}
          self._error('提交失败', detail.message || '请重试')
          return
        }
        // mini 端惯例：成功返回裸 dict {id, status, photo_count, ...}
        var data = res.data || {}
        var count = data.photo_count === null || data.photo_count === undefined
          ? self.data.totalPhotos : data.photo_count
        self._requestId = ''
        self.setData({
          successVisible: true,
          submitted: true,
          successTitle: '提交成功',
          successDesc: '已上传 ' + count + ' 张照片'
        })
        setTimeout(function () { self._reset() }, 1800)
      },
      fail: function () {
        self.setData({ state: 'ready' })
        self._error('网络异常', '请检查网络后重试')
      }
    })
  },

  // ─── 复位与提示 ──────────────────────────────

  // 提交成功后回 idle，接着扫下一单；批次令牌 +1 作废在途的图片下载
  _reset: function () {
    this._imageBatch += 1
    this._requestId = ''
    this._qrRaw = ''
    this._pendingUpload = null
    this._pendingVideo = null
    this.setData({
      state: 'idle',
      uploading: false, pendingMedia: false, mediaError: '', mediaStage: '',
      record: null,
      items: [],
      wholePhotos: [],
      wholeVideos: [],
      editVersion: 0,
      totalPhotos: 0,
      canSubmit: false,
      submitted: false,
      statusText: '',
      remark: '',
      successVisible: false
    })
  },

  _error: function (title, message) {
    this.setData({ errorVisible: true, errorTitle: title, errorMessage: message })
  },

  onErrorTap: function () { this.setData({ errorVisible: false }) },
  onSuccessClose: function () { this._reset() },

  // catch 需要真实存在的方法名，catchtap="" 挡不住冒泡（点弹层内容会误关）
  noop: function () {}
}, videoMethods))
