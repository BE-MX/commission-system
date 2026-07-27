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

  onLoad: function (options) {
    var info = wx.getSystemInfoSync()
    this.setData({
      statusBarHeight: info.statusBarHeight || 20,
      userName: (app.globalData.userInfo && app.globalData.userInfo.name) || ''
    })
    // 从主扫码页按 ARK-D 前缀分流过来时直接带着 itemId/sign，不用再扫一次
    if (options && options.itemId && options.sign) {
      this._loadItem(parseInt(options.itemId), options.sign)
    }
  },

  onShow: function () {
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
          // 扫到外贸卡就送回外贸报工页，别让工人自己判断扫错了哪种卡
          if (/^ARK-P:/.test(raw)) {
            self.setData({ state: 'idle' })
            wx.navigateBack()
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

  // 图片端点要鉴权，<image src> 带不了 header，用 downloadFile 带上再显示
  _loadImages: function (data) {
    var self = this
    var paths = []
    var fields = ['hairstyle_images', 'color_images', 'style_images', 'remark_images']
    for (var i = 0; i < fields.length; i++) {
      var list = data[fields[i]] || []
      for (var j = 0; j < list.length; j++) paths.push(list[j])
    }
    if (!paths.length) { self.setData({ images: [] }); return }

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
          if (pending === 0) self.setData({ images: loaded })
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
    this.setData({ state: 'submitting' })
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/scan/submit',
      method: 'POST',
      header: this._header(),
      data: {
        item_id: this.data.scanned.item_id,
        progress_id: this.data.nextStep.progress_id,
        qty: qty
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
        if (data.item_finished) text += '（这批货全部做完了）'
        else if (data.step_finished) text += '（本道工序做满）'
        self.setData({
          state: 'idle', successVisible: true, successText: text,
          scanned: null, nextStep: null, images: []
        })
        self._loadHistory()
        setTimeout(function () { self.setData({ successVisible: false }) }, 2500)
      },
      fail: function () {
        self._showError('网络异常', '请检查网络后重试')
        self.setData({ state: 'showing-confirm' })
      }
    })
  },

  onCancelTap: function () {
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

  // ─── 错误处理 ──────────────────────────────

  _showError: function (title, detail) {
    var self = this
    this.setData({ errorVisible: true, errorTitle: title, errorDetail: detail })
    setTimeout(function () { self.setData({ errorVisible: false }) }, 3000)
  },

  onErrorClose: function () {
    this.setData({ errorVisible: false })
  }
})
