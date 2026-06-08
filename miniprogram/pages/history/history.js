// pages/history/history.js — 零 import

var app = getApp()

var SWIPE_THRESHOLD = 60
var SWIPE_OPEN = -72

Page({
  data: {
    records: [],
    page: 1,
    pageSize: 20,
    loading: false,
    refreshing: false,
    noMore: false,
    statusBarHeight: 20,
    showFilter: false,
    dateStart: '',
    dateEnd: '',
    keyword: '',
    orderNo: '',
    revokeVisible: false,
    revokeProgressId: null,
    revokeProcessName: '',
    revokeIndex: -1,
    submitting: false,
    submittingText: '撤销提交中',
    resultVisible: false,
    resultSuccess: true,
    resultTitle: '',
    resultMessage: ''
  },

  _swipeStartX: 0,
  _swipeStartY: 0,
  _swipeOpenIndex: -1,

  onLoad: function () {
    var sysInfo = wx.getSystemInfoSync()
    this.setData({ statusBarHeight: sysInfo.statusBarHeight || 20 })
    this.loadRecords()
  },

  onBack: function () {
    wx.navigateBack({ delta: 1 })
  },

  // ─── 筛选操作 ──────────────────────────────

  onToggleFilter: function () {
    this.setData({ showFilter: !this.data.showFilter })
  },

  onDateStartChange: function (e) {
    this.setData({ dateStart: e.detail.value })
  },

  onDateEndChange: function (e) {
    this.setData({ dateEnd: e.detail.value })
  },

  onKeywordInput: function (e) {
    this.setData({ keyword: e.detail.value })
  },

  onOrderNoInput: function (e) {
    this.setData({ orderNo: e.detail.value })
  },

  onResetFilter: function () {
    this.setData({
      dateStart: '',
      dateEnd: '',
      keyword: '',
      orderNo: ''
    })
  },

  onSearch: function () {
    this.setData({ page: 1, noMore: false, records: [] })
    this.loadRecords()
  },

  // ─── 数据加载 ──────────────────────────────

  loadRecords: function () {
    if (this.data.loading || this.data.noMore) return
    var self = this
    this.setData({ loading: true })

    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }

    var url = app.globalData.baseUrl + '/api/mini/scan/history/all?page=' + this.data.page + '&page_size=' + this.data.pageSize
    if (this.data.dateStart) url += '&date_start=' + this.data.dateStart
    if (this.data.dateEnd) url += '&date_end=' + this.data.dateEnd
    if (this.data.keyword) url += '&keyword=' + encodeURIComponent(this.data.keyword)
    if (this.data.orderNo) url += '&order_no=' + encodeURIComponent(this.data.orderNo)

    wx.request({
      url: url,
      method: 'GET',
      header: header,
      timeout: 30000,
      success: function (res) {
        if (res.statusCode === 200) {
          var newRecords = (res.data.records || []).map(function (r) {
            r._swipeX = 0
            r._animating = false
            return r
          })
          self.setData({
            records: self.data.page === 1 ? newRecords : self.data.records.concat(newRecords),
            noMore: newRecords.length < self.data.pageSize,
            loading: false
          })
        } else {
          self.setData({ loading: false })
        }
      },
      fail: function () {
        self.setData({ loading: false })
      }
    })
  },

  onLoadMore: function () {
    if (this.data.noMore || this.data.loading) return
    this.setData({ page: this.data.page + 1 })
    this.loadRecords()
  },

  onRefresh: function () {
    this.setData({ refreshing: true, page: 1, noMore: false })
    this.loadRecords()
    this.setData({ refreshing: false })
  },

  // ─── 左滑手势 ──────────────────────────────

  _closeSwipe: function () {
    if (this._swipeOpenIndex >= 0) {
      var list = this.data.records
      if (list && list[this._swipeOpenIndex]) {
        var key = 'records[' + this._swipeOpenIndex + ']._swipeX'
        var keyA = 'records[' + this._swipeOpenIndex + ']._animating'
        var obj = {}
        obj[key] = 0
        obj[keyA] = true
        this.setData(obj)
      }
    }
    this._swipeOpenIndex = -1
  },

  onSwipeStart: function (e) {
    this._swipeStartX = e.touches[0].clientX
    this._swipeStartY = e.touches[0].clientY
  },

  onSwipeMove: function (e) {
    var dx = e.touches[0].clientX - this._swipeStartX
    var dy = e.touches[0].clientY - this._swipeStartY
    if (Math.abs(dy) > Math.abs(dx)) return

    var idx = e.currentTarget.dataset.index

    if (this._swipeOpenIndex >= 0 && this._swipeOpenIndex !== idx) {
      this._closeSwipe()
    }

    var offsetX = Math.min(0, Math.max(SWIPE_OPEN, dx))
    var key = 'records[' + idx + ']._swipeX'
    var keyA = 'records[' + idx + ']._animating'
    var obj = {}
    obj[key] = offsetX
    obj[keyA] = false
    this.setData(obj)
  },

  onSwipeEnd: function (e) {
    var dx = e.changedTouches[0].clientX - this._swipeStartX
    var idx = e.currentTarget.dataset.index

    var shouldOpen = dx < -SWIPE_THRESHOLD
    var targetX = shouldOpen ? SWIPE_OPEN : 0
    var key = 'records[' + idx + ']._swipeX'
    var keyA = 'records[' + idx + ']._animating'
    var obj = {}
    obj[key] = targetX
    obj[keyA] = true
    this.setData(obj)

    if (shouldOpen) {
      this._swipeOpenIndex = idx
    } else {
      if (this._swipeOpenIndex === idx) {
        this._swipeOpenIndex = -1
      }
    }
  },

  // ─── 撤销操作 ──────────────────────────────

  onRevokeTap: function (e) {
    var progressId = e.currentTarget.dataset.progressId
    var processName = e.currentTarget.dataset.processName
    var index = e.currentTarget.dataset.index
    this.setData({
      revokeVisible: true,
      revokeProgressId: progressId,
      revokeProcessName: processName,
      revokeIndex: index
    })
  },

  onRevokeCancel: function () {
    this.setData({ revokeVisible: false, revokeProgressId: null, revokeProcessName: '' })
    this._closeSwipe()
  },

  onRevokeConfirm: function () {
    var self = this
    var progressId = this.data.revokeProgressId
    this.setData({ revokeVisible: false, submitting: true, submittingText: '撤销提交中' })

    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }

    wx.request({
      url: app.globalData.baseUrl + '/api/mini/scan/revoke',
      method: 'POST',
      data: { progress_id: progressId },
      header: header,
      timeout: 30000,
      success: function (res) {
        self.setData({ submitting: false })
        if (res.statusCode >= 400) {
          var detail = (res.data && res.data.detail) || {}
          self.setData({
            resultVisible: true,
            resultSuccess: false,
            resultTitle: '撤销失败',
            resultMessage: detail.message || '操作失败，请重试'
          })
          return
        }
        self.setData({
          resultVisible: true,
          resultSuccess: true,
          resultTitle: '撤销成功',
          resultMessage: res.data.message || '已撤销'
        })
        self._swipeOpenIndex = -1
        // 刷新列表
        self.setData({ page: 1, noMore: false, records: [] })
        self.loadRecords()

        setTimeout(function () {
          self.setData({ resultVisible: false })
        }, 2000)
      },
      fail: function () {
        self.setData({ submitting: false })
        self.setData({
          resultVisible: true,
          resultSuccess: false,
          resultTitle: '网络异常',
          resultMessage: '无法连接服务器，请重试'
        })
      }
    })
  },

  onResultTap: function () {
    this.setData({ resultVisible: false })
  }
})
