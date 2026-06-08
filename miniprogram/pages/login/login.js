// pages/login/login.js — 零 import

var app = getApp()

Page({
  data: {
    openId: '',
    identifier: '',
    isLoggingIn: false,
    loading: false,
    devMode: false,
    devIdentifier: ''
  },

  onLoad: function () {
    var isDev = app.globalData.baseUrl.indexOf('127.0.0.1') >= 0 || app.globalData.baseUrl.indexOf('localhost') >= 0
    this.setData({ devMode: isDev })
    if (!isDev) {
      this._autoLogin()
    }
  },

  _autoLogin: function () {
    var self = this
    this.setData({ isLoggingIn: true })
    wx.login({
      success: function (loginRes) {
        wx.request({
          url: app.globalData.baseUrl + '/api/mini/auth/login',
          method: 'POST',
          data: { code: loginRes.code },
          header: { 'Content-Type': 'application/json' },
          timeout: 30000,
          success: function (res) {
            if (res.statusCode === 200 && res.data.bound) {
              app.saveAuth(res.data.token, res.data.user)
              wx.switchTab({ url: '/pages/scan/scan' })
            } else if (res.statusCode === 200) {
              self.setData({ openId: res.data.open_id, isLoggingIn: false })
            } else {
              self.setData({ isLoggingIn: false })
              wx.showToast({ title: '登录失败', icon: 'error' })
            }
          },
          fail: function () {
            self.setData({ isLoggingIn: false })
            wx.showToast({ title: '登录失败，请重试', icon: 'error' })
          }
        })
      },
      fail: function () {
        self.setData({ isLoggingIn: false })
        wx.showToast({ title: 'wx.login 失败', icon: 'error' })
      }
    })
  },

  onIdentifierInput: function (e) {
    this.setData({ identifier: e.detail.value })
  },

  onDevIdentifierInput: function (e) {
    this.setData({ devIdentifier: e.detail.value })
  },

  onBind: function () {
    var self = this
    var identifier = this.data.identifier.trim()
    if (!identifier) return

    this.setData({ loading: true })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/auth/bind',
      method: 'POST',
      data: { open_id: this.data.openId, identifier: identifier },
      header: { 'Content-Type': 'application/json' },
      timeout: 30000,
      success: function (res) {
        self.setData({ loading: false })
        if (res.statusCode === 200) {
          app.saveAuth(res.data.token, res.data.user)
          wx.switchTab({ url: '/pages/scan/scan' })
        } else {
          var msg = (res.data && res.data.detail && res.data.detail.message) || '绑定失败'
          wx.showToast({ title: msg, icon: 'none', duration: 3000 })
        }
      },
      fail: function () {
        self.setData({ loading: false })
        wx.showToast({ title: '网络错误', icon: 'error' })
      }
    })
  },

  onDevLogin: function () {
    var self = this
    var id = this.data.devIdentifier.trim()
    if (!id) return

    this.setData({ loading: true })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/auth/dev-login',
      method: 'POST',
      data: { identifier: id },
      header: { 'Content-Type': 'application/json' },
      timeout: 30000,
      success: function (res) {
        self.setData({ loading: false })
        if (res.statusCode === 200) {
          app.saveAuth(res.data.token, res.data.user)
          wx.switchTab({ url: '/pages/scan/scan' })
        } else {
          var msg = (res.data && res.data.detail && res.data.detail.message) || '登录失败'
          wx.showToast({ title: msg, icon: 'none', duration: 3000 })
        }
      },
      fail: function () {
        self.setData({ loading: false })
        wx.showToast({ title: '网络错误', icon: 'error' })
      }
    })
  }
})
