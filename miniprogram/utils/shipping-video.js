// 相册视频交互；照片和视频分开计数，复用页面的鉴权上传与编辑状态。
var sc = require('./shipping-check')

module.exports = {
  onWholeVideoTap: function () { this._chooseVideo(null) },
  onItemVideoTap: function (e) { this._chooseVideo(e.currentTarget.dataset.itemId) },
  _chooseVideo: function (itemId) {
    if (this.data.submitted || this.data.state !== 'ready' || this.data.uploading) return
    var self = this
    wx.chooseMedia({
      count: 1, mediaType: ['video'], sourceType: ['album'],
      success: function (res) {
        var file = res.tempFiles && res.tempFiles[0]
        if (!file) return
        if (file.size > 100 * 1024 * 1024) {
          self._error('视频过大', '请选择不超过100MB的视频')
          return
        }
        self._upload(file.tempFilePath, itemId, 'video')
      },
      fail: function (err) {
        if ((err.errMsg || '').indexOf('cancel') < 0) self._error('无法选择视频', '请检查相册权限后重试')
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
    if (this.data.submitted || this.data.state !== 'ready' || this.data.uploading) return
    var id = e.currentTarget.dataset.videoId
    var self = this
    var version = this.data.editVersion
    var batch = this._imageBatch
    wx.showModal({ title: '删除视频', content: '确定删除这段视频吗？',
      success: function (res) {
        if (!res.confirm || batch !== self._imageBatch || self.data.submitted || self.data.uploading) return
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
