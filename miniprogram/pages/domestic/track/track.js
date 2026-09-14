// pages/domestic/track/track.js — 订单进度（小程序码免登录查看）
// 客户微信扫「订单进度码」直达本页：不要求登录，凭码里的签名看这一单。
// 页面上没有搜索、没有扫码入口——没有码就查不了别的订单。
// 2026-09-14 起只展示店面名称、客户单号、顾客名称和产品工艺参数/发型/颜色；
// 价格、订单状态、产品状态、工序进度服务端已不下发。
var app = getApp()

Page({
  data: {
    statusBarHeight: 20,
    loading: true,
    errorText: '',
    order: null
  },

  onLoad: function (options) {
    var info = wx.getSystemInfoSync()
    this.setData({ statusBarHeight: info.statusBarHeight || 20 })
    // 扫小程序码进来时 scene 是 URL 编码过的
    var scene = options && options.scene ? decodeURIComponent(options.scene) : ''
    this._scene = scene
    if (!scene) {
      this.setData({ loading: false, errorText: '请扫描订单进度码打开本页' })
      return
    }
    this._query()
  },

  // 内容会变（比如补图），客户会反复看同一张码——下拉即刷新
  onPullDownRefresh: function () {
    if (this._scene) this._query()
    else wx.stopPullDownRefresh()
  },

  _query: function () {
    var self = this
    this.setData({ loading: !this.data.order, errorText: '' })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/track?scene=' + encodeURIComponent(this._scene),
      method: 'GET',
      timeout: 30000,
      success: function (res) {
        wx.stopPullDownRefresh()
        self.setData({ loading: false })
        if (res.statusCode !== 200) {
          var detail = (res.data && res.data.detail) || {}
          // 手上有旧内容时保留着，别因为一次刷新失败把整页清成"请重新扫码"
          if (!self.data.order) self.setData({ errorText: detail.message || '查询失败，请重试' })
          return
        }
        self.setData({ order: self._decorate(res.data || {}), errorText: '' })
      },
      fail: function () {
        wx.stopPullDownRefresh()
        self.setData({ loading: false })
        if (!self.data.order) self.setData({ errorText: '网络异常，请检查网络后重试' })
      }
    })
  },

  // 视图态在这里算好，wxml 里不放表达式
  _decorate: function (order) {
    var items = order.items || []
    for (var i = 0; i < items.length; i++) {
      var attrs = items[i].attrs || {}
      items[i].attrText = [attrs.craft, attrs.net_color, attrs.size, attrs.length, attrs.density].filter(Boolean).join(' / ')
      var imageFields = ['hairstyle_images', 'color_images', 'style_images']
      var imageUrls = []
      for (var f = 0; f < imageFields.length; f++) {
        var paths = items[i][imageFields[f]] || []
        for (var k = 0; k < paths.length; k++) {
          imageUrls.push(app.globalData.baseUrl + '/api/mini/domestic/track-image?scene=' +
            encodeURIComponent(this._scene) + '&rel_path=' + encodeURIComponent(paths[k]))
        }
      }
      items[i].imageUrls = imageUrls
    }
    order.items = items
    return order
  },

  onPreviewImage: function (e) {
    var item = this.data.order.items[e.currentTarget.dataset.item]
    var index = e.currentTarget.dataset.index
    wx.previewImage({ current: item.imageUrls[index], urls: item.imageUrls })
  }
})
