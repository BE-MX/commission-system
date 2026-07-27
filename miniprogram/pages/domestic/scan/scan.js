// pages/domestic/scan/scan.js — 内贸扫码报工（按数量，可拆批）
// 零 import，纯回调（与 pages/scan/scan.js 同一套风格）
var app = getApp()

var BLOCK_HINTS = {
  ITEM_NOT_FOUND: '找不到这张卡对应的订单明细',
  NO_ROUTE: '这个产品还没配工艺路线，请联系跟单',
  ORDER_TERMINATED: '订单已终止，不能报工',
  ALL_DONE: '这批货所有工序都做完了',
  NOT_ASSIGNED: '你没有被分配到这道工序',
  NOTHING_REPORTABLE: '上一道工序还没做出可接的数量，请稍后再扫',
  SIGN_INVALID: '二维码无效，请扫内贸流转卡'
}

Page({
  data: {
    statusBarHeight: 20,
    state: 'idle',            // idle | scanning | validating | showing-confirm | submitting
    loading: false,
    userName: '',
    todayCount: 0,
    todayQty: 0,
    todayRecords: [],

    scanned: null,            // 扫码返回的明细信息
    nextStep: null,           // 该报的工序
    reportQty: 0,             // 本次报工数量（默认可报全量，拆批就调小）
    maxQty: 0,
    images: [],               // 参考图临时路径

    errorVisible: false,
    errorTitle: '',
    errorDetail: '',
    successVisible: false,
    successText: ''
  },

  _imageBatch: 0,
  _requestId: '',

  onLoad: function (options) {
    var info = wx.getSystemInfoSync()
    this.setData({
      statusBarHeight: info.statusBarHeight || 20,
      userName: (app.globalData.userInfo && app.globalData.userInfo.name) || ''
    })
    // 本页现在是 tabBar 页，正常不会带 query；保留这条是为了兼容旧的
    // navigateTo 链接（比如别处写死的路径）
    if (options && options.itemId && options.sign) {
      this._loadItem(parseInt(options.itemId), options.sign)
    }
  },

  onShow: function () {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1, hide: false })
    }
    // switchTab 不能带 query 参数，所以外贸页扫到 ARK-D 码时把 payload
    // 暂存在 globalData 里，切过来后在这里取出并清掉（只消费一次）
    var pending = app.globalData.pendingDomesticScan
    if (pending) {
      app.globalData.pendingDomesticScan = null
      this._loadItem(pending.itemId, pending.sign)
    }
    this._loadHistory()
  },

  _header: function () {
    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }
    return header
  },

  // ─── 扫码 ──────────────────────────────

  onScanTap: function () {
    var self = this
    this.setData({ state: 'scanning' })
    wx.scanCode({
      scanType: ['qrCode'],
      success: function (scan) {
        var raw = scan.result || ''
        var match = raw.match(/^ARK-D:(\d+):([a-f0-9]+)$/)
        if (!match) {
          // 扫到外贸卡：说清楚发生了什么再切到外贸报工，别让工人一头雾水
          if (/^ARK-P:/.test(raw)) {
            self.setData({ state: 'idle' })
            wx.showToast({ title: '这是外贸流转卡，帮你切到外贸报工', icon: 'none', duration: 2000 })
            setTimeout(function () { wx.switchTab({ url: '/pages/scan/scan' }) }, 1200)
            return
          }
          self._showError('二维码无效', BLOCK_HINTS.SIGN_INVALID)
          self.setData({ state: 'idle' })
          return
        }
        self._loadItem(parseInt(match[1]), match[2])
      },
      fail: function () {
        self.setData({ state: 'idle' })
      }
    })
  },

  _loadItem: function (itemId, sign) {
    var self = this
    this.setData({ state: 'validating', loading: true })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/scan/' + itemId + '?sign=' + sign,
      method: 'GET',
      header: this._header(),
      success: function (res) {
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) {
          var detail = (res.data && res.data.detail) || {}
          self._showError('扫码失败', detail.message || '请重试')
          self.setData({ state: 'idle', loading: false })
          return
        }
        var data = res.data || {}
        if (!data.can_submit) {
          self._showError('暂时不能报工', data.block_message || BLOCK_HINTS[data.block_reason] || '请联系跟单')
          self.setData({ state: 'idle', loading: false, scanned: data })
          self._loadImages(data)
          return
        }
        self.setData({
          state: 'showing-confirm',
          loading: false,
          scanned: data,
          nextStep: data.next_step,
          reportQty: data.next_step.reportable_qty,
          maxQty: data.next_step.reportable_qty
        })
        self._loadImages(data)
      },
      fail: function () {
        self._showError('网络异常', '请检查网络后重试')
        self.setData({ state: 'idle', loading: false })
      }
    })
  },

  // 图片端点要鉴权，<image src> 带不了 header，用 downloadFile 带上再显示。
  // 批次令牌不能省：连扫两张卡时先发起的那批（图可能 20MB）后完成会覆盖，
  // 工人就会对着上一张卡的参考图做活。
  _loadImages: function (data) {
    var self = this
    var batch = ++this._imageBatch
    var paths = []
    var fields = ['hairstyle_images', 'color_images', 'style_images', 'remark_images']
    for (var i = 0; i < fields.length; i++) {
      var list = data[fields[i]] || []
      for (var j = 0; j < list.length; j++) paths.push(list[j])
    }
    self.setData({ images: [] })
    if (!paths.length) return

    var loaded = []
    var pending = paths.length
    paths.forEach(function (path) {
      wx.downloadFile({
        url: app.globalData.baseUrl + '/api/mini/domestic/images/' + path,
        header: self._header(),
        success: function (res) {
          if (res.statusCode === 200) loaded.push(res.tempFilePath)
        },
        complete: function () {
          pending -= 1
          if (pending === 0 && batch === self._imageBatch) {
            self.setData({ images: loaded })
          }
        }
      })
    })
  },

  onPreviewImage: function (e) {
    var index = e.currentTarget.dataset.index
    wx.previewImage({ current: this.data.images[index], urls: this.data.images })
  },

  // ─── 数量调整 ──────────────────────────────

  onQtyInput: function (e) {
    var value = parseInt(e.detail.value) || 0
    this.setData({ reportQty: value })
  },

  onQtyBlur: function () {
    var qty = this.data.reportQty
    if (qty < 1) qty = 1
    if (qty > this.data.maxQty) qty = this.data.maxQty
    this.setData({ reportQty: qty })
  },

  onQtyMinus: function () {
    if (this.data.reportQty > 1) this.setData({ reportQty: this.data.reportQty - 1 })
  },

  onQtyPlus: function () {
    if (this.data.reportQty < this.data.maxQty) this.setData({ reportQty: this.data.reportQty + 1 })
  },

  onQtyAll: function () {
    this.setData({ reportQty: this.data.maxQty })
  },

  // ─── 提交 ──────────────────────────────

  onConfirmTap: function () {
    var self = this
    var qty = this.data.reportQty
    if (!(qty > 0) || qty > this.data.maxQty) {
      this._showError('数量不对', '本次最多能报 ' + this.data.maxQty + ' 件')
      return
    }
    // 幂等键在同一次确认里复用：弱网下"服务端已提交、响应丢了"时工人再点一次，
    // 服务端认出是同一笔，返回首次结果而不是再记一笔
    if (!this._requestId) {
      this._requestId = Date.now() + '-' + Math.random().toString(36).slice(2, 12)
    }

    this.setData({ state: 'submitting' })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/scan/submit',
      method: 'POST',
      header: this._header(),
      data: {
        item_id: this.data.scanned.item_id,
        progress_id: this.data.nextStep.progress_id,
        qty: qty,
        request_id: this._requestId
      },
      success: function (res) {
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) {
          var detail = (res.data && res.data.detail) || {}
          self._showError('报工失败', detail.message || '请重试')
          self.setData({ state: 'showing-confirm' })
          return
        }
        var data = res.data || {}
        var text = '已报 ' + data.reported_qty + ' 件 · ' + data.process_name
        if (data.replayed) text = '这笔已经报过了 · ' + text
        else if (data.item_finished) text += '（这批货全部做完了）'
        else if (data.step_finished) text += '（本道工序做满）'
        self._requestId = ''   // 本笔收尾，下次确认换新的幂等键
        self.setData({
          state: 'idle', successVisible: true, successText: text,
          scanned: null, nextStep: null, images: []
        })
        self._setTabBarHidden(true)
        self._loadHistory()
        setTimeout(function () {
          self.setData({ successVisible: false })
          self._setTabBarHidden(false)
        }, 2500)
      },
      fail: function () {
        self._showError('网络异常', '请检查网络后重试')
        self.setData({ state: 'showing-confirm' })
      }
    })
  },

  onCancelTap: function () {
    this._requestId = ''
    this.setData({ state: 'idle', scanned: null, nextStep: null, images: [] })
  },

  // ─── 今日记录 ──────────────────────────────

  _loadHistory: function () {
    var self = this
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/history',
      method: 'GET',
      header: this._header(),
      success: function (res) {
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) return
        var data = res.data || {}
        self.setData({
          todayCount: data.today_count || 0,
          todayQty: data.today_qty || 0,
          todayRecords: data.records || []
        })
      }
    })
  },

  onRevokeTap: function (e) {
    var self = this
    var logId = e.currentTarget.dataset.logId
    wx.showModal({
      title: '撤销这次报工？',
      content: '撤销后这道工序的完成数量会相应减少。',
      confirmText: '撤销',
      confirmColor: '#E53935',
      success: function (modal) {
        if (!modal.confirm) return
        wx.request({
          url: app.globalData.baseUrl + '/api/mini/domestic/scan/revoke',
          method: 'POST',
          header: self._header(),
          data: { log_id: logId },
          success: function (res) {
            if (res.statusCode === 401) { app.logout(); return }
            if (res.statusCode !== 200) {
              var detail = (res.data && res.data.detail) || {}
              self._showError('撤销失败', detail.message || '请重试')
              return
            }
            wx.showToast({ title: '已撤销', icon: 'success' })
            self._loadHistory()
          }
        })
      }
    })
  },

  onOrdersTap: function () {
    wx.navigateTo({ url: '/pages/domestic/orders/orders' })
  },

  onSwitchModuleTap: function () {
    // tabBar 页的页面栈是空的，只能 reLaunch 回落地页
    wx.reLaunch({ url: '/pages/entry/entry' })
  },

  // ─── 错误处理 ──────────────────────────────

  // 底栏是 fixed z-index 999，弹层遮罩盖不住它（跨组件 z-index 不可比），
  // 所以弹层期间直接把底栏收起来——外贸页弹确认框时也是这么做的
  _setTabBarHidden: function (hidden) {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ hide: hidden })
    }
  },

  _showError: function (title, detail) {
    var self = this
    this.setData({ errorVisible: true, errorTitle: title, errorDetail: detail })
    this._setTabBarHidden(true)
    setTimeout(function () {
      self.setData({ errorVisible: false })
      self._setTabBarHidden(false)
    }, 3000)
  },

  onErrorClose: function () {
    this.setData({ errorVisible: false })
    this._setTabBarHidden(false)
  }
})
