var app = getApp()
var beijingNow = require('../../utils/time').beijingNow
var navigation = require('../../utils/navigation')

Page({
  data: { statusBarHeight: 20, userName: '', avatarLetter: '', greeting: '你好，', entries: [], loading: true, error: '' },
  onLoad: function () {
    this.setData({ statusBarHeight: wx.getSystemInfoSync().statusBarHeight || 20 })
  },
  onShow: function () { this.loadEntries() },
  onHide: function () { this._requestId = (this._requestId || 0) + 1 },
  onUnload: function () { this._requestId = (this._requestId || 0) + 1 },
  loadEntries: function () {
    if (!app.globalData.token) { wx.reLaunch({ url: '/pages/login/login' }); return }
    var self = this
    var requestId = this._requestId = (this._requestId || 0) + 1
    var token = app.globalData.token
    var hour = beijingNow().getHours()
    var name = (app.globalData.userInfo || {}).name || ''
    app.globalData.allowedEntries = []
    this.setData({ loading: true, error: '', entries: [], userName: name, avatarLetter: name.charAt(0),
      greeting: hour < 6 ? '夜里好，' : hour < 11 ? '早上好，' : hour < 14 ? '中午好，' : hour < 18 ? '下午好，' : '晚上好，' })
    function current() { return self._requestId === requestId && app.globalData.token === token }
    function failed() { if (current()) self.setData({ loading: false, error: '功能加载失败，请检查网络后重试' }) }
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/auth/verify',
      header: { Authorization: 'Bearer ' + token }, timeout: 15000,
      success: function (res) {
        if (!current()) return
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200 || !res.data || !res.data.valid || !Array.isArray(res.data.allowed_entries)) { failed(); return }
        var entries = navigation.visibleEntries(res.data.allowed_entries)
        app.globalData.allowedEntries = entries.map(function (entry) { return entry.id })
        var user = res.data.user || app.globalData.userInfo
        if (user) { app.globalData.userInfo = user; wx.setStorageSync('ark_user', user) }
        var userName = (user || {}).name || ''
        self.setData({ loading: false, entries: entries, userName: userName, avatarLetter: userName.charAt(0) })
      },
      fail: failed
    })
  },
  onEntryTap: function (event) {
    if (!this.data.loading && !this.data.error) navigation.open(event.currentTarget.dataset.id)
  },
  onLogoutTap: function () {
    wx.showModal({
      title: '退出登录',
      content: '退出后需点击微信登录重新进入，已绑定的工号会保留。确定退出吗？',
      confirmText: '退出',
      confirmColor: '#E53935',
      success: function (res) {
        if (res.confirm) app.logout({ manual: true })
      }
    })
  }
})
