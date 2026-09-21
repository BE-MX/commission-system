var app = getApp()
var navigation = require('../../../utils/navigation')
Page({
  data: { statusBarHeight: 20, loading: false, errorText: '', unit: null },
  onLoad: function (options) {
    if (!navigation.guard('domestic')) return
    this.setData({ statusBarHeight: wx.getSystemInfoSync().statusBarHeight || 20 })
    this._unitId = options && options.unitId
    this._sign = options && options.sign
    if (!/^\d+$/.test(this._unitId || '') || !/^[a-f0-9]+$/.test(this._sign || '')) {
      this._unitId = null
      this._sign = null
      this.setData({ errorText: '逐件码参数无效，请返回重新扫码' })
      return
    }
    this._query()
  },
  onShow: function () { navigation.guard('domestic') },
  onPullDownRefresh: function () {
    if (this._unitId && this._sign) this._query()
    else wx.stopPullDownRefresh()
  },
  _query: function () {
    if (!navigation.guard('domestic')) return
    var self = this
    this.setData({ loading: true, errorText: '' })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/unit-history/' + this._unitId + '?sign=' + encodeURIComponent(this._sign),
      header: { Authorization: 'Bearer ' + app.globalData.token }, timeout: 30000,
      success: function (res) {
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) {
          self.setData({ errorText: (res.data && res.data.detail && res.data.detail.message) || '记录查询失败，请下拉重试', unit: null })
          return
        }
        var unit = res.data
        ;(unit.steps || []).forEach(function (step) {
          ;(step.records || []).forEach(function (row) {
            row.timeText = (row.at || '').replace('T', ' ').slice(0, 19)
            row.revokedText = (row.revoked_at || '').replace('T', ' ').slice(0, 19)
          })
        })
        self.setData({ unit: unit })
      },
      fail: function () { self.setData({ errorText: '网络异常，请下拉重试', unit: null }) },
      complete: function () { self.setData({ loading: false }); wx.stopPullDownRefresh() }
    })
  },
  onBack: function () { wx.navigateBack({ fail: function () { wx.switchTab({ url: '/pages/domestic/scan/scan' }) } }) }
})
