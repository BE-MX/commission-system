// app.js
App({
  globalData: {
    userInfo: null,
    token: null,
    baseUrl: 'http://10.91.3.182:8001'    // 本地开发（真机调试用）
    // baseUrl: 'https://leshine.work'             // 生产/体验版
  },

  onLaunch: function () {
    var token = wx.getStorageSync('ark_token')
    var userInfo = wx.getStorageSync('ark_user')
    if (token && userInfo) {
      this.globalData.token = token
      this.globalData.userInfo = userInfo
    } else {
      wx.redirectTo({ url: '/pages/login/login' })
    }
  },

  logout: function () {
    this.globalData.token = null
    this.globalData.userInfo = null
    wx.removeStorageSync('ark_token')
    wx.removeStorageSync('ark_user')
    wx.redirectTo({ url: '/pages/login/login' })
  },

  saveAuth: function (token, user) {
    this.globalData.token = token
    this.globalData.userInfo = user
    wx.setStorageSync('ark_token', token)
    wx.setStorageSync('ark_user', user)
  }
})
