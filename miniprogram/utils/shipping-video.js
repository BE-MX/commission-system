// 拍摄/相册视频压缩上传；照片和视频分开计数，复用页面的鉴权上传与编辑状态。
var sc = require('./shipping-check')

module.exports = {
  onWholeVideoTap: function () { this._chooseVideo(null) },
  onItemVideoTap: function (e) { this._chooseVideo(e.currentTarget.dataset.itemId) },
  onWholeAlbumVideoTap: function () { this._chooseVideo(null, 'album') },
  onItemAlbumVideoTap: function (e) { this._chooseVideo(e.currentTarget.dataset.itemId, 'album') },
  _chooseVideo: function (itemId, sourceType) {
    if (this.data.submitted || this.data.state !== 'ready' || this.data.uploading || this.data.pendingMedia) return
    if (typeof wx.compressVideo !== 'function') { this._error('微信版本过旧', '请更新微信后重试'); return }
    var self = this
    var batch = this._imageBatch
    this.setData({ uploading: true })
    wx.chooseMedia({
      count: 1, mediaType: ['video'], sourceType: [sourceType || 'camera'], camera: 'back',
      success: function (res) {
        if (batch !== self._imageBatch) return
        self.setData({ uploading: false })
        var file = res.tempFiles && res.tempFiles[0]
        if (!file) return
        self._pendingVideo = { filePath: file.tempFilePath, itemId: itemId }
        self._compressPendingVideo()
      },
      fail: function (err) {
        if (batch !== self._imageBatch) return
        self.setData({ uploading: false })
        if ((err.errMsg || '').indexOf('cancel') < 0) self._error('无法选择视频', '请检查相机和相册权限后重试')
      }
    })
  },
  _mediaFailure: function (title, message) {
    wx.hideLoading()
    this.setData({ uploading: false, pendingMedia: true, mediaStage: '', mediaError: message })
    this._error(title, message)
  },
  _compressPendingVideo: function () {
    var self = this, pending = this._pendingVideo, batch = this._imageBatch
    if (!pending || this.data.uploading || this.data.submitted || this.data.state !== 'ready') return
    this.setData({ uploading: true, pendingMedia: false, mediaError: '', mediaStage: '压缩视频中，请保持页面在前台', mediaItemId: pending.itemId == null ? null : pending.itemId })
    wx.compressVideo({ src: pending.filePath, quality: 'medium',
      success: function (compressed) {
        if (batch !== self._imageBatch) return
        wx.getFileInfo({ filePath: compressed.tempFilePath,
          success: function (info) {
            if (batch !== self._imageBatch) return
            if (!info.size || info.size > 100 * 1024 * 1024) {
              self._mediaFailure('视频过大', '压缩后视频仍超过100MB或内容为空，请放弃后分段拍摄'); return
            }
            self._pendingVideo = null
            self.setData({ uploading: false })
            self._upload(compressed.tempFilePath, pending.itemId, 'video')
          },
          fail: function () { if (batch === self._imageBatch) self._mediaFailure('读取视频失败', '请重试压缩或放弃此视频') }
        })
      },
      fail: function () { if (batch === self._imageBatch) self._mediaFailure('视频压缩失败', '视频已保留，请重试压缩并上传') }
    })
  },
  onRetryMedia: function () {
    if (this.data.uploading || this.data.submitted || this.data.state !== 'ready') return
    this.setData({ pendingMedia: false, errorVisible: false })
    if (this._pendingVideo) this._compressPendingVideo()
    else if (this._pendingUpload) {
      var p = this._pendingUpload
      this._upload(p.filePath, p.itemId, p.mediaType, p)
    }
  },
  onDiscardMedia: function () {
    if (this.data.uploading || !this.data.pendingMedia) return
    var self = this, batch = this._imageBatch
    wx.showModal({ title: '放弃待处理文件', content: '尚未上传的文件将不再保留。上传结果未确认时，请刷新核对已上传内容。',
      success: function (res) {
        if (!res.confirm || batch !== self._imageBatch || self.data.uploading) return
        self._pendingVideo = null; self._pendingUpload = null
        self.setData({ pendingMedia: false, mediaError: '', mediaStage: '', errorVisible: false })
      }
    })
  },
  _appendVideo: function (video) {
    var change = {}
    if (video.itemId == null) change['wholeVideos[' + this.data.wholeVideos.length + ']'] = video
    else {
      for (var i = 0; i < this.data.items.length; i++) {
        if (String(this.data.items[i].item_id) === String(video.itemId)) {
          change['items[' + i + '].videos[' + this.data.items[i].videos.length + ']'] = video
          break
        }
      }
    }
    this.setData(change)
  },
  _videoById: function (id) {
    var videos = this.data.wholeVideos.slice()
    this.data.items.forEach(function (item) { videos = videos.concat(item.videos) })
    return videos.find(function (video) { return String(video.id) === String(id) })
  },
  onPreviewVideo: function (e) {
    if (this.data.uploading) return
    var video = this._videoById(e.currentTarget.dataset.videoId)
    if (!video) return
    var self = this
    function preview(url) { wx.previewMedia({ sources: [{ url: url, type: 'video' }] }) }
    if (video.url) { preview(video.url); return }
    var app = getApp()
    var batch = this._imageBatch
    wx.showLoading({ title: '加载视频…', mask: true })
    wx.downloadFile({
      url: sc.imageUrl(app.globalData.baseUrl, video.filePath),
      header: this._header(), timeout: 300000,
      success: function (res) {
        if (res.statusCode === 401) { app.logout(); return }
        if (batch !== self._imageBatch) return
        if (res.statusCode !== 200) { self._error('视频加载失败', '请重试'); return }
        preview(res.tempFilePath)
      },
      fail: function () { self._error('视频加载失败', '请检查网络后重试') },
      complete: function () { wx.hideLoading() }
    })
  },
  onDeleteVideo: function (e) {
    if (this.data.submitted || this.data.state !== 'ready' || this.data.uploading || this.data.pendingMedia) return
    var id = e.currentTarget.dataset.videoId
    var self = this
    var version = this.data.editVersion
    var batch = this._imageBatch
    wx.showModal({ title: '删除视频', content: '确定删除这段视频吗？',
      success: function (res) {
        if (!res.confirm || batch !== self._imageBatch || self.data.submitted || self.data.uploading || self.data.pendingMedia) return
        var app = getApp()
        self.setData({ uploading: true })
        wx.request({
          url: app.globalData.baseUrl + '/api/mini/shipping-inspection/videos/' + id + '?edit_version=' + version,
          method: 'DELETE', header: self._header(), timeout: 30000,
          success: function (response) {
            if (response.statusCode === 401) { app.logout(); return }
            if (response.statusCode >= 400) {
              var detail = (response.data && response.data.detail) || {}
              self._error('删除失败', detail.message || '请刷新核对后重试')
              return
            }
            if (batch !== self._imageBatch) return
            function keep(video) { return String(video.id) !== String(id) }
            self.setData({ wholeVideos: self.data.wholeVideos.filter(keep), items: self.data.items.map(function (item) {
              return Object.assign({}, item, { videos: item.videos.filter(keep) })
            }) })
          },
          fail: function () { self._error('删除失败', '请刷新核对后重试') },
          complete: function () { self.setData({ uploading: false }) }
        })
      }
    })
  }
}
