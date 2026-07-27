// pages/entry/entry.js — 登录后的模块选择（外贸报工 / 内贸报工）
// 零 import，纯回调（与其余页面同一套风格）
var app = getApp()

Page({
  data: {
    statusBarHeight: 20,
    userName: '',
    greeting: '你好，',
    entered: false
  },

  onLoad: function () {
    var info = wx.getSystemInfoSync()
    var hour = new Date().getHours()
    var greeting = '你好，'
    if (hour < 6) greeting = '夜里好，'
    else if (hour < 11) greeting = '早上好，'
    else if (hour < 14) greeting = '中午好，'
    else if (hour < 18) greeting = '下午好，'
    else greeting = '晚上好，'

    this.setData({
      statusBarHeight: info.statusBarHeight || 20,
      userName: (app.globalData.userInfo && app.globalData.userInfo.name) || '',
      greeting: greeting
    })
  },

  onShow: function () {
    // 每次回到本页重放入场：从模块退回来时也有方向感，而不是硬切
    var self = this
    this.setData({ entered: false })
    setTimeout(function () { self.setData({ entered: true }) }, 30)
  },

  onExportTap: function () {
    // 外贸是 tabBar 页，只能 switchTab
    wx.switchTab({ url: '/pages/scan/scan' })
  },

  onDomesticTap: function () {
    // 内贸页现在也是 tabBar 页，同样只能 switchTab
    wx.switchTab({ url: '/pages/domestic/scan/scan' })
  },

  onLookupTap: function () {
    wx.navigateTo({ url: '/pages/domestic/lookup/lookup' })
  },

  onLogoutTap: function () {
    wx.showModal({
      title: '退出登录',
      content: '退出后需要重新绑定工号。确定退出吗？',
      confirmText: '退出',
      confirmColor: '#E53935',
      success: function (res) {
        if (res.confirm) app.logout()
      }
    })
  }
})
