// pages/photo/photo.js — 零 import
var app = getApp()

Page({
  data: {
    statusBarHeight: 20,
    imagePath: ''
  },

  onLoad: function () {
    var sysInfo = wx.getSystemInfoSync()
    this.setData({ statusBarHeight: sysInfo.statusBarHeight || 20 })
  },

  onShow: function () {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1 })
    }
  },

  onChooseImage: function () {
    var self = this
    wx.chooseMedia({
      count: 1,
      mediaType: ['image'],
      sourceType: ['camera', 'album'],
      sizeType: ['compressed'],
      success: function (res) {
        if (res.tempFiles && res.tempFiles.length > 0) {
          self.setData({ imagePath: res.tempFiles[0].tempFilePath })
        }
      }
    })
  },

  onClearImage: function () {
    this.setData({ imagePath: '' })
  }
})
