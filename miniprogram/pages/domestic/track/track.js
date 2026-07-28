// pages/domestic/track/track.js — 订单进度（小程序码免登录查看）
// 客户/员工微信扫「订单进度码」直达本页：不要求登录，凭码里的签名看这一单。
// 页面上没有搜索、没有扫码入口——没有码就查不了别的订单。
var app = getApp()

// 工序三态 → 颜色与文案（与订单速查同一套判定）
function stateOf(step) {
  if (step.completed_qty >= step.order_qty && step.order_qty > 0) return ['done', '已完成']
  if (step.completed_qty > 0) return ['doing', '进行中']
  if (step.reportable_qty > 0) return ['ready', '可开工']
  return ['wait', '等上道']
}

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

  // 进度会变，客户会反复看同一张码——下拉即刷新
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
          // 手上有旧进度时保留着，别因为一次刷新失败把整页清成"请重新扫码"
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

  // 视图态在这里算好，wxml 里不放表达式（与订单速查同一套）
  _decorate: function (order) {
    // 下拉刷新后保留用户已展开的明细，不折回去
    var prevExpanded = {}
    var prevItems = (this.data.order && this.data.order.items) || []
    for (var p = 0; p < prevItems.length; p++) prevExpanded[prevItems[p].id] = prevItems[p].expanded
    var items = order.items || []
    for (var i = 0; i < items.length; i++) {
      var steps = items[i].steps || []
      var view = []
      for (var j = 0; j < steps.length; j++) {
        var s = steps[j]
        var st = stateOf(s)
        view.push({
          progress_id: s.progress_id,
          step_order: s.step_order,
          process_name: s.process_name,
          completed_qty: s.completed_qty,
          order_qty: s.order_qty,
          reportable_qty: s.reportable_qty,
          last_reported_by: s.last_reported_by,
          last_report_qty: s.last_report_qty,
          last_reported_at: (s.last_reported_at || '').replace('T', ' ').slice(0, 16),
          pct: s.order_qty ? Math.round(s.completed_qty / s.order_qty * 100) : 0,
          state: st[0],
          stateText: st[1]
        })
      }
      items[i].stepView = view
      items[i].expanded = prevExpanded[items[i].id] || false   // 默认只出前 3 道
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
  }
})
