// pages/overview/overview.js — 报工总览页（全用户，按日期+工序分组）

var app = getApp()

Page({
  data: {
    dates: [],
    loading: true,
    showDetail: false,
    detailRecords: [],
    detailProcessName: '',
    detailDate: '',
    dateStart: '',
    dateEnd: '',
    showFilter: false
  },

  onLoad: function () {
    this.loadData()
  },

  onPullDownRefresh: function () {
    this.loadData()
    wx.stopPullDownRefresh()
  },

  loadData: function () {
    var self = this
    self.setData({ loading: true })

    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }

    var url = app.globalData.baseUrl + '/api/mini/scan/overview'
    var params = []
    if (self.data.dateStart) params.push('date_start=' + self.data.dateStart)
    if (self.data.dateEnd) params.push('date_end=' + self.data.dateEnd)
    if (params.length) url += '?' + params.join('&')

    wx.request({
      url: url,
      method: 'GET',
      header: header,
      timeout: 30000,
      success: function (res) {
        if (res.statusCode === 401) {
          app.logout()
          return
        }
        if (res.statusCode === 200) {
          self.setData({ dates: res.data.dates || [], loading: false })
        } else {
          self.setData({ loading: false })
        }
      },
      fail: function () {
        self.setData({ loading: false })
      }
    })
  },

  // ── 分组点击 → 查看明细 ──

  onGroupTap: function (e) {
    var date = e.currentTarget.dataset.date
    var processId = e.currentTarget.dataset.processId
    var processName = e.currentTarget.dataset.processName
    var self = this

    self.setData({ loading: true })

    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }

    wx.request({
      url: app.globalData.baseUrl + '/api/mini/scan/overview/detail?date=' + date + '&process_id=' + processId,
      method: 'GET',
      header: header,
      timeout: 30000,
      success: function (res) {
        self.setData({ loading: false })
        if (res.statusCode === 401) {
          app.logout()
          return
        }
        if (res.statusCode === 200) {
          self.setData({
            showDetail: true,
            detailRecords: res.data.records || [],
            detailProcessName: processName,
            detailDate: date
          })
        }
      },
      fail: function () {
        self.setData({ loading: false })
      }
    })
  },

  onCloseDetail: function () {
    this.setData({ showDetail: false, detailRecords: [] })
  },

  // ── 筛选 ──

  onToggleFilter: function () {
    this.setData({ showFilter: !this.data.showFilter })
  },

  onDateStartChange: function (e) {
    this.setData({ dateStart: e.detail.value })
  },

  onDateEndChange: function (e) {
    this.setData({ dateEnd: e.detail.value })
  },

  onSearch: function () {
    this.setData({ showFilter: false })
    this.loadData()
  },

  onResetFilter: function () {
    this.setData({ dateStart: '', dateEnd: '', showFilter: false })
    this.loadData()
  },

  onBack: function () {
    wx.navigateBack()
  }
})
