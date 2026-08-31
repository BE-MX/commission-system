// pages/domestic/scan/scan.js — 内贸扫码报工
// 状态机、左滑撤销、各类遮罩与外贸报工页（pages/scan/scan.js）一一对应，
// 内贸独有的只有「报工数量」和图文要求，都收在 domestic-sheet 里。
// 零 import，纯回调（与其余页面同一套风格）
var app = getApp()

var SWIPE_THRESHOLD = 60
var SWIPE_OPEN = -72

var BLOCK_MESSAGES = {
  SIGN_INVALID: '二维码无效，请扫内贸流转卡',
  ITEM_NOT_FOUND: '找不到这张卡对应的订单明细',
  NO_ROUTE: '这个产品还没配工艺路线，请联系跟单',
  ORDER_TERMINATED: '订单已终止或已删除，不能报工',
  ORDER_DRAFT: '订单还是草稿，请跟单提交后再报工',
  UNIT_QR_REQUIRED: '当前账号是逐件扫码模式，请扫描 A1-01 这类单件二维码',
  ALL_DONE: '这批货所有工序都做完了',
  NOT_ASSIGNED: '你没有被分配到这道工序',
  NOTHING_REPORTABLE: '上一道工序还没做出可接的数量，请稍后再扫'
}

Page({
  data: {
    state: 'idle',              // idle | showing-confirm
    statusBarHeight: 20,
    userName: '',
    avatarLetter: '',
    todayCount: 0,
    todayQty: 0,
    todayRecords: [],

    scanned: null,              // 扫码返回的明细
    nextStep: null,             // 该报的工序
    images: [],                 // 参考图临时路径

    submitting: false,
    loading: false,
    successVisible: false,
    successTitle: '报工成功',
    successMessage: '',
    errorVisible: false,
    errorTitle: '',
    errorMessage: '',
    revokeVisible: false,
    revokeLogId: null,
    revokeProcessName: '',
    revokeIndex: -1
  },

  // ─── 左滑状态 ──────────────────────────────
  _swipeStartX: 0,
  _swipeStartY: 0,
  _swipeOpenIndex: -1,
  _imageBatch: 0,
  _requestId: '',

  onLoad: function (options) {
    var info = wx.getSystemInfoSync()
    this.setData({ statusBarHeight: info.statusBarHeight || 20 })
    // 本页是 tabBar 页，正常不带 query；保留兼容旧的 navigateTo 链接
    if (options && options.itemId && options.sign) {
      this._loadItem(parseInt(options.itemId), options.sign)
    }
  },

  onShow: function () {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 1, hide: false })
    }
    var user = app.globalData.userInfo
    if (user) {
      var name = user.name || ''
      this.setData({ userName: name, avatarLetter: name ? name.charAt(0) : '' })
    }
    // switchTab 不能带 query：外贸页扫到 ARK-D 码时把 payload 存 globalData，这里取走
    var pending = app.globalData.pendingDomesticScan
    if (pending) {
      app.globalData.pendingDomesticScan = null
      if (pending.unitId) this._loadUnit(pending.unitId, pending.sign)
      else this._loadItem(pending.itemId, pending.sign)
    }
    if (this.data.state === 'idle') this.loadTodayHistory()
  },

  onPullDownRefresh: function () {
    this.loadTodayHistory()
    wx.stopPullDownRefresh()
  },

  _header: function () {
    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) header['Authorization'] = 'Bearer ' + app.globalData.token
    return header
  },

  // 底栏是 fixed 的 83px，且跨组件 z-index 不可比 —— 弹层期间必须把它收起来，
  // 否则正好压住确认弹层底部的「取消 / 确认报 N 件」。
  // 单一真相：任何遮罩/弹层在场就收起，避免逐个转场漏调。
  _syncTabBar: function () {
    var d = this.data
    var covered = d.state === 'showing-confirm' || d.loading || d.submitting ||
                  d.successVisible || d.errorVisible || d.revokeVisible
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ hide: covered })
    }
  },

  // ─── 今日记录 ──────────────────────────────

  loadTodayHistory: function () {
    var self = this
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/history',
      method: 'GET',
      header: this._header(),
      timeout: 30000,
      success: function (res) {
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) return
        var data = res.data || {}
        self.setData({
          todayCount: data.today_count || 0,
          todayQty: data.today_qty || 0,
          todayRecords: data.records || []
        })
        self._swipeOpenIndex = -1
      }
    })
  },

  // ─── 扫码 ──────────────────────────────

  onScanTap: function () {
    var self = this
    wx.scanCode({
      scanType: ['qrCode'],
      success: function (scan) {
        var raw = scan.result || ''
        var unit = raw.match(/^ARK-DU:(\d+):([a-f0-9]+)$/)
        if (unit) {
          self._loadUnit(parseInt(unit[1]), unit[2])
          return
        }
        var m = raw.match(/^ARK-D:(\d+):([a-f0-9]+)$/)
        if (!m) {
          // 扫到外贸卡：说清楚再切过去，别让工人一头雾水
          if (/^ARK-P:/.test(raw)) {
            wx.showToast({ title: '这是外贸流转卡，帮你切到外贸报工', icon: 'none', duration: 2000 })
            setTimeout(function () { wx.switchTab({ url: '/pages/scan/scan' }) }, 1200)
            return
          }
          self._error('二维码无效', BLOCK_MESSAGES.SIGN_INVALID)
          return
        }
        self._loadItem(parseInt(m[1]), m[2])
      }
    })
  },

  _loadItem: function (itemId, sign) {
    this._loadScan('/api/mini/domestic/scan/' + itemId + '?sign=' + sign, '')
  },

  _loadUnit: function (unitId, sign) {
    this._loadScan('/api/mini/domestic/unit-scan/' + unitId + '?sign=' + sign, sign)
  },

  _loadScan: function (path, unitSign) {
    var self = this
    this.setData({ loading: true })
    this._syncTabBar()
    wx.request({
      url: app.globalData.baseUrl + path,
      method: 'GET',
      header: this._header(),
      timeout: 30000,
      success: function (res) {
        self.setData({ loading: false })
        self._syncTabBar()
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode !== 200) {
          var detail = (res.data && res.data.detail) || {}
          self._error('扫码失败', detail.message || '请重试')
          return
        }
        var data = res.data || {}
        data.unit_sign = unitSign || ''
        if (!data.can_submit) {
          self._error('暂时不能报工',
            data.block_message || BLOCK_MESSAGES[data.block_reason] || '请联系跟单')
          return
        }
        self._requestId = ''
        self.setData({ state: 'showing-confirm', scanned: data, nextStep: data.next_step })
        self._syncTabBar()
        self._loadImages(data)
      },
      fail: function () {
        self.setData({ loading: false })
        self._syncTabBar()
        self._error('网络异常', '请检查网络后重试')
      }
    })
  },

  // 图片端点要鉴权，<image src> 带不了 header，用 downloadFile 带上再显示。
  // 批次令牌不能省：连扫两张卡时先发起的那批后完成会覆盖，工人会对着上一张卡的图做活。
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
        success: function (res) { if (res.statusCode === 200) loaded.push(res.tempFilePath) },
        complete: function () {
          pending -= 1
          if (pending === 0 && batch === self._imageBatch) self.setData({ images: loaded })
        }
      })
    })
  },

  // ─── 确认弹层回调 ──────────────────────────────

  onCancelConfirm: function () {
    this._requestId = ''
    this.setData({ state: 'idle', scanned: null, nextStep: null, images: [] })
    this._syncTabBar()
  },

  onInvalidQty: function (e) {
    this._error('数量不对', e.detail.message || ('本次最多能报 ' + (e.detail.maxQty || 0) + ' 件'))
  },

  onConfirmSubmit: function (e) {
    var self = this
    var qty = e.detail.qty
    var outcomes = e.detail.outcomes || null
    // 幂等键在同一次确认里复用：弱网下"已提交但响应丢了"时再点一次不会报两次
    if (!this._requestId) {
      this._requestId = Date.now() + '-' + Math.random().toString(36).slice(2, 12)
    }
    this.setData({ submitting: true })
    this._syncTabBar()
    var submitData = {
      item_id: this.data.scanned.item_id,
      progress_id: this.data.nextStep.progress_id,
      qty: qty,
      unit_id: this.data.scanned.report_mode === 'unit' ? this.data.scanned.unit_id : null,
      unit_sign: this.data.scanned.report_mode === 'unit' ? this.data.scanned.unit_sign : null,
      request_id: this._requestId
    }
    if (outcomes) submitData.outcomes = outcomes
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/scan/submit',
      method: 'POST',
      header: this._header(),
      timeout: 30000,
      data: submitData,
      success: function (res) {
        self.setData({ submitting: false })
        self._syncTabBar()
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode >= 400) {
          var detail = (res.data && res.data.detail) || {}
          self._error('报工失败', detail.message || '请重试')
          return
        }
        var data = res.data || {}
        var codes = (data.unit_codes || []).join('、')
        var msg = data.process_name + ' · ' + data.reported_qty + ' 件' + (codes ? ' · ' + codes : '')
        var title = '报工成功'
        if (data.replayed) title = '这笔已经报过了'
        else if (data.item_finished) msg += '，这批货全部做完了'
        else if (data.step_finished) msg += '，本道工序做满'
        self._requestId = ''
        self.setData({
          state: 'idle', scanned: null, nextStep: null, images: [],
          successVisible: true, successTitle: title, successMessage: msg
        })
        self.loadTodayHistory()
        setTimeout(function () { self.setData({ successVisible: false }); self._syncTabBar() }, 2200)
      },
      fail: function () {
        self.setData({ submitting: false })
        self._syncTabBar()
        self._error('网络异常', '请检查网络后重试')
      }
    })
  },

  // ─── 左滑撤销 ──────────────────────────────

  onSwipeStart: function (e) {
    this._swipeStartX = e.touches[0].clientX
    this._swipeStartY = e.touches[0].clientY
  },

  onSwipeMove: function (e) {
    var dx = e.touches[0].clientX - this._swipeStartX
    var dy = e.touches[0].clientY - this._swipeStartY
    if (Math.abs(dy) > Math.abs(dx)) return          // 纵向滑动不处理

    var idx = e.currentTarget.dataset.index
    if (this._swipeOpenIndex >= 0 && this._swipeOpenIndex !== idx) this._closeSwipe()

    var obj = {}
    obj['todayRecords[' + idx + ']._swipeX'] = Math.min(0, Math.max(SWIPE_OPEN, dx))
    obj['todayRecords[' + idx + ']._animating'] = false
    this.setData(obj)
  },

  onSwipeEnd: function (e) {
    var dx = e.changedTouches[0].clientX - this._swipeStartX
    var idx = e.currentTarget.dataset.index
    var shouldOpen = dx < -SWIPE_THRESHOLD
    var obj = {}
    obj['todayRecords[' + idx + ']._swipeX'] = shouldOpen ? SWIPE_OPEN : 0
    obj['todayRecords[' + idx + ']._animating'] = true
    this.setData(obj)
    if (shouldOpen) this._swipeOpenIndex = idx
    else if (this._swipeOpenIndex === idx) this._swipeOpenIndex = -1
  },

  _closeSwipe: function () {
    if (this._swipeOpenIndex < 0) return
    var obj = {}
    obj['todayRecords[' + this._swipeOpenIndex + ']._swipeX'] = 0
    obj['todayRecords[' + this._swipeOpenIndex + ']._animating'] = true
    this.setData(obj)
    this._swipeOpenIndex = -1
  },

  onRevokeTap: function (e) {
    this.setData({
      revokeVisible: true,
      revokeLogId: e.currentTarget.dataset.logId,
      revokeProcessName: e.currentTarget.dataset.processName,
      revokeIndex: e.currentTarget.dataset.index
    })
    this._syncTabBar()
  },

  onRevokeCancel: function () {
    this.setData({ revokeVisible: false, revokeLogId: null, revokeProcessName: '' })
    this._syncTabBar()
    this._closeSwipe()
  },

  onRevokeConfirm: function () {
    var self = this
    var logId = this.data.revokeLogId
    this.setData({ revokeVisible: false, submitting: true })
    this._syncTabBar()
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/domestic/scan/revoke',
      method: 'POST',
      header: this._header(),
      timeout: 30000,
      data: { log_id: logId },
      success: function (res) {
        self.setData({ submitting: false })
        self._syncTabBar()
        if (res.statusCode === 401) { app.logout(); return }
        if (res.statusCode >= 400) {
          var detail = (res.data && res.data.detail) || {}
          self._error('撤销失败', detail.message || '请重试')
          return
        }
        self._closeSwipe()
        self.setData({
          successVisible: true, successTitle: '已撤销',
          successMessage: '该工序完成数量已相应减少'
        })
        self.loadTodayHistory()
        setTimeout(function () { self.setData({ successVisible: false }); self._syncTabBar() }, 1800)
      },
      fail: function () {
        self.setData({ submitting: false })
        self._syncTabBar()
        self._error('网络异常', '请检查网络后重试')
      }
    })
  },

  // ─── 导航与提示 ──────────────────────────────

  onOrdersTap: function () { wx.navigateTo({ url: '/pages/domestic/orders/orders' }) },
  onAllRecordsTap: function () { wx.navigateTo({ url: '/pages/domestic/orders/orders' }) },
  onSwitchModuleTap: function () { wx.reLaunch({ url: '/pages/entry/entry' }) },

  _error: function (title, message) {
    this.setData({ errorVisible: true, errorTitle: title, errorMessage: message })
    this._syncTabBar()
  },

  // catch 需要真实存在的方法名，catchtap="" 挡不住冒泡（点弹层内容会误关）
  noop: function () {},

  onErrorTap: function () { this.setData({ errorVisible: false }); this._syncTabBar() },
  onSuccessTap: function () { this.setData({ successVisible: false }); this._syncTabBar() }
})
