// app.js
App({
  globalData: {
    userInfo: null,
    token: null,
    // 外贸页扫到 ARK-D 码时的暂存位：switchTab 不能带 query 参数，
    // 内贸页 onShow 取走后立即置回 null（只消费一次）
    pendingDomesticScan: null,
    // baseUrl: 'http://10.91.3.182:8001'    // 本地开发（真机调试用）
    baseUrl: 'https://leshine.work'             // 生产/体验版
  },

  onLaunch: function () {
    var token = wx.getStorageSync('ark_token')
    var userInfo = wx.getStorageSync('ark_user')
    if (token && userInfo) {
      this.globalData.token = token
      this.globalData.userInfo = userInfo
    } else {
      // 扫「订单进度码」进来的客户没有方舟账号，免登录页不许踢去登录
      var launch = wx.getLaunchOptionsSync()
      if ((launch.path || '').indexOf('pages/domestic/track/track') === 0) return
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
