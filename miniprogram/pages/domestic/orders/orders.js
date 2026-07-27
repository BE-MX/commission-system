// pages/domestic/orders/orders.js — 内贸订单进度（车间/跟单查看）
// 零 import，纯回调（同 pages/history/history.js 的分页写法）
var app = getApp()

Page({
  data: {
    orders: [],
    page: 1,
    pageSize: 20,
    total: 0,
    noMore: false,
    loading: false,
    keyword: '',
    statusFilter: '',
    statusOptions: [
      { value: '', label: '全部' },
      { value: 1, label: '生产中' },
      { value: 2, label: '已完工' },
      { value: 3, label: '已发货' }
    ],
    detail: null,
    detailVisible: false
  },

  onLoad: function () {
    this._load(true)
  },

  onReachBottom: function () {
    if (!this.data.noMore && !this.data.loading) this._load(false)
  },

  _header: function () {
    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }
    return header
  },

  _load: function (reset) {
    var self = this
    var page = reset ? 1 : this.data.page + 1
    this.setData({ loading: true })

    var url = app.globalData.baseUrl + '/api/mini/domestic/orders?page=' + page + '&page_size=' + this.data.pageSize
    if (this.data.keyword) url += '&keyword=' + encodeURIComponent(this.data.keyword)
    if (this.data.statusFilter !== '') url += '&status=' + this.data.statusFilter

    wx.request({
      url: url,
      method: 'GET',
      header: this._header(),
      success: function (res) {
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) { self.setData({ loading: false }); return }
        var data = res.data || {}
        var items = data.items || []
        var merged = reset ? items : self.data.orders.concat(items)
        self.setData({
          orders: merged,
          page: page,
          total: data.total || 0,
          noMore: merged.length >= (data.total || 0),
          loading: false
        })
      },
      fail: function () {
        self.setData({ loading: false })
        wx.showToast({ title: '网络异常', icon: 'none' })
      }
    })
  },

  onKeywordInput: function (e) {
    this.setData({ keyword: e.detail.value })
  },

  onSearchTap: function () {
    this._load(true)
  },

  onStatusTap: function (e) {
    this.setData({ statusFilter: e.currentTarget.dataset.value })
    this._load(true)
  },

  onOrderTap: function (e) {
    var self = this
    var orderId = e.currentTarget.dataset.id
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/orders/' + orderId,
      method: 'GET',
      header: this._header(),
      success: function (res) {
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) {
          wx.showToast({ title: '加载失败', icon: 'none' })
          return
        }
        self.setData({ detail: res.data, detailVisible: true })
      }
    })
  },

  onDetailClose: function () {
    this.setData({ detailVisible: false, detail: null })
  },

  // 弹层内部点击不冒泡到遮罩（catchtap 需要一个真实存在的方法）
  noop: function () {}
})
