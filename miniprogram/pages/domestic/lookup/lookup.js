// pages/domestic/lookup/lookup.js — 订单速查
// 一个输入框吃三种：系统单号 / 客户订单号 / 扫码，交给服务端分辨。
// 零 import，纯回调（与其余页面同一套风格）
var app = getApp()
var routing = require('../../../utils/domestic-routing')

// 工序三态 → 颜色与文案（车间抬眼要能立刻分辨）
function stateOf(step) {
  if (step.passed_qty >= step.order_qty && step.order_qty > 0) return ['done', '已完成']
  if (step.passed_qty > 0) return ['doing', '进行中']
  if (step.reportable_qty > 0) return ['ready', '可开工']
  return ['wait', '等上道']
}

Page({
  data: {
    statusBarHeight: 20,
    keyword: '',
    loading: false,
    errorText: '',
    order: null
  },

  onLoad: function (options) {
    var info = wx.getSystemInfoSync()
    this.setData({ statusBarHeight: info.statusBarHeight || 20 })
    if (options && options.code) {
      this.setData({ keyword: options.code })
      this._query(options.code)
    }
  },

  _header: function () {
    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) header['Authorization'] = 'Bearer ' + app.globalData.token
    return header
  },

  onInput: function (e) { this.setData({ keyword: e.detail.value }) },

  onSearch: function () {
    var kw = (this.data.keyword || '').trim()
    if (!kw) {
      this.setData({ errorText: '请先输入订单号，或点扫码' })
      return
    }
    this._query(kw)
  },

  onScanTap: function () {
    var self = this
    wx.scanCode({
      scanType: ['qrCode'],
      success: function (res) {
        var raw = res.result || ''
        self.setData({ keyword: raw })
        self._query(raw)     // 二维码原文直接交后端验签定位
      }
    })
  },

  _query: function (code) {
    var self = this
    this.setData({ loading: true, errorText: '', order: null })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/lookup?code=' + encodeURIComponent(code),
      method: 'GET',
      header: this._header(),
      timeout: 30000,
      success: function (res) {
        self.setData({ loading: false })
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) {
          var detail = (res.data && res.data.detail) || {}
          self.setData({ errorText: detail.message || '查询失败，请重试' })
          return
        }
        self.setData({ order: self._decorate(res.data || {}) })
      },
      fail: function () {
        self.setData({ loading: false, errorText: '网络异常，请检查网络后重试' })
      }
    })
  },

  // 视图态在这里算好，wxml 里不放表达式（小程序模板不支持函数调用）
  _decorate: function (order) {
    var items = order.items || []
    for (var i = 0; i < items.length; i++) {
      var steps = items[i].steps || []
      var view = []
      for (var j = 0; j < steps.length; j++) {
        var s = steps[j]
        var progress = routing.decorateProgress(s)
        var st = stateOf(s)
        view.push({
          progress_id: s.progress_id,
          step_order: s.step_order,
          process_name: s.process_name,
          completed_qty: progress.completedQty,
          skipped_qty: progress.skippedQty,
          passed_qty: progress.passedQty,
          order_qty: s.order_qty,
          reportable_qty: s.reportable_qty,
          last_reported_by: s.last_reported_by,
          last_report_qty: s.last_report_qty,
          last_reported_at: (s.last_reported_at || '').replace('T', ' ').slice(0, 16),
          pct: progress.percent,
          state: st[0],
          stateText: st[1]
        })
      }
      items[i].stepView = view
      items[i].expanded = false   // 默认只出前 3 道
    }
    order.items = items
    return order
  },

  onToggleSteps: function (e) {
    var idx = e.currentTarget.dataset.idx
    var key = 'order.items[' + idx + '].expanded'
    var obj = {}
    obj[key] = !this.data.order.items[idx].expanded
    this.setData(obj)
  },

  onBack: function () {
    var stack = getCurrentPages()
    if (stack.length > 1) wx.navigateBack()
    else wx.reLaunch({ url: '/pages/entry/entry' })
  }
})
