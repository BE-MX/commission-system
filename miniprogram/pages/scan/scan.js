// pages/scan/scan.js — 零 import，纯回调

var app = getApp()

var SWIPE_THRESHOLD = 60
var SWIPE_OPEN = -72

// block_reason 提示文案
var BLOCK_MESSAGES = {
  SIGN_INVALID: '二维码无效，请重新扫描',
  ORDER_PRODUCT_NOT_FOUND: '找不到该产品记录，请联系管理员',
  PROCESS_ALREADY_DONE: '该工序已完成',
  NOT_YOUR_PROCESS: '您负责的不是该工序',
  NOT_ASSIGNED: '您未被分配此工序，请联系管理员'
}

Page({
  data: {
    state: 'idle',
    statusBarHeight: 20,
    userName: '',
    avatarLetter: '',
    todayCount: 0,
    todayRecords: [],
    productInfo: null,
    nextProcess: null,
    allProcesses: [],
    canSubmit: false,
    submitting: false,
    submittingText: '报工提交中',
    loading: false,
    successVisible: false,
    successTitle: '报工成功',
    successMessage: '',
    errorVisible: false,
    errorTitle: '',
    errorMessage: '',
    revokeVisible: false,
    revokeProgressId: null,
    revokeProcessName: '',
    revokeList: '',
    revokeIndex: -1
  },

  // ─── 左滑状态 ──────────────────────────────
  _swipeStartX: 0,
  _swipeStartY: 0,
  _swipeOpenIndex: -1,
  _swipeOpenList: '',

  onLoad: function () {
    var sysInfo = wx.getSystemInfoSync()
    var isDev = app.globalData.baseUrl.indexOf('127.0.0.1') >= 0 || app.globalData.baseUrl.indexOf('localhost') >= 0
    this.setData({ statusBarHeight: sysInfo.statusBarHeight || 20 })
  },

  onShow: function () {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 0 })
    }
    var user = app.globalData.userInfo
    if (user) {
      var letter = (user.name || '?').charAt(0)
      this.setData({ userName: user.name || '', avatarLetter: letter })
    }
    if (this.data.state === 'idle') {
      this.loadTodayHistory()
    }
  },

  onPullDownRefresh: function () {
    this.loadTodayHistory()
    wx.stopPullDownRefresh()
  },

  // ─── 今日记录 ──────────────────────────────

  loadTodayHistory: function () {
    var self = this
    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }
    wx.request({
      url: app.globalData.baseUrl + '/api/mini/scan/history',
      method: 'GET',
      header: header,
      timeout: 30000,
      success: function (res) {
        if (res.statusCode === 401) {
          app.logout()
          return
        }
        if (res.statusCode === 200) {
          // 给每条记录加 _swipeX
          var records = (res.data.records || []).map(function (r) {
            r._swipeX = 0
            r._animating = false
            return r
          })
          self.setData({
            todayRecords: records,
            todayCount: res.data.today_count || 0
          })
        }
      },
      fail: function () {}
    })
  },

  // ─── 左滑手势 ──────────────────────────────

  _closeSwipe: function () {
    if (this._swipeOpenIndex >= 0 && this._swipeOpenList) {
      var listKey = this._swipeOpenList === 'today' ? 'todayRecords' : 'records'
      var list = this.data[listKey]
      if (list && list[this._swipeOpenIndex]) {
        var key = listKey + '[' + this._swipeOpenIndex + ']._swipeX'
        var keyA = listKey + '[' + this._swipeOpenIndex + ']._animating'
        this.setData({})  // 触发更新
        var obj = {}
        obj[key] = 0
        obj[keyA] = true
        this.setData(obj)
      }
    }
    this._swipeOpenIndex = -1
    this._swipeOpenList = ''
  },

  onSwipeStart: function (e) {
    this._swipeStartX = e.touches[0].clientX
    this._swipeStartY = e.touches[0].clientY
  },

  onSwipeMove: function (e) {
    var dx = e.touches[0].clientX - this._swipeStartX
    var dy = e.touches[0].clientY - this._swipeStartY
    // 纵向滑动不处理
    if (Math.abs(dy) > Math.abs(dx)) return

    var idx = e.currentTarget.dataset.index
    var listType = e.currentTarget.dataset.list
    var listKey = listType === 'today' ? 'todayRecords' : 'records'

    // 关闭其他已打开的
    if (this._swipeOpenIndex >= 0 && (this._swipeOpenIndex !== idx || this._swipeOpenList !== listType)) {
      this._closeSwipe()
    }

    var offsetX = Math.min(0, Math.max(SWIPE_OPEN, dx))
    var key = listKey + '[' + idx + ']._swipeX'
    var keyA = listKey + '[' + idx + ']._animating'
    var obj = {}
    obj[key] = offsetX
    obj[keyA] = false
    this.setData(obj)
  },

  onSwipeEnd: function (e) {
    var dx = e.changedTouches[0].clientX - this._swipeStartX
    var idx = e.currentTarget.dataset.index
    var listType = e.currentTarget.dataset.list
    var listKey = listType === 'today' ? 'todayRecords' : 'records'

    var shouldOpen = dx < -SWIPE_THRESHOLD
    var targetX = shouldOpen ? SWIPE_OPEN : 0
    var key = listKey + '[' + idx + ']._swipeX'
    var keyA = listKey + '[' + idx + ']._animating'
    var obj = {}
    obj[key] = targetX
    obj[keyA] = true
    this.setData(obj)

    if (shouldOpen) {
      this._swipeOpenIndex = idx
      this._swipeOpenList = listType
    } else {
      if (this._swipeOpenIndex === idx && this._swipeOpenList === listType) {
        this._swipeOpenIndex = -1
        this._swipeOpenList = ''
      }
    }
  },

  onRevokeTap: function (e) {
    var progressId = e.currentTarget.dataset.progressId
    var processName = e.currentTarget.dataset.processName
    var list = e.currentTarget.dataset.list
    var index = e.currentTarget.dataset.index
    this.setData({
      revokeVisible: true,
      revokeProgressId: progressId,
      revokeProcessName: processName,
      revokeList: list,
      revokeIndex: index
    })
  },

  onRevokeCancel: function () {
    this.setData({ revokeVisible: false, revokeProgressId: null, revokeProcessName: '' })
    this._closeSwipe()
  },

  onRevokeConfirm: function () {
    var self = this
    var progressId = this.data.revokeProgressId
    this.setData({ revokeVisible: false, submitting: true, submittingText: '撤销提交中' })

    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }

    wx.request({
      url: app.globalData.baseUrl + '/api/mini/scan/revoke',
      method: 'POST',
      data: { progress_id: progressId },
      header: header,
      timeout: 30000,
      success: function (res) {
        self.setData({ submitting: false })
        if (res.statusCode === 401) {
          app.logout()
          return
        }
        if (res.statusCode >= 400) {
          var detail = (res.data && res.data.detail) || {}
          self.setData({
            errorVisible: true,
            errorTitle: '撤销失败',
            errorMessage: detail.message || '操作失败，请重试'
          })
          return
        }
        self.setData({
          successVisible: true,
          successTitle: '撤销成功',
          successMessage: res.data.message || '撤销成功'
        })
        // 刷新列表
        if (self.data.revokeList === 'today') {
          self.loadTodayHistory()
        }
        self._swipeOpenIndex = -1
        self._swipeOpenList = ''

        setTimeout(function () {
          self.setData({ successVisible: false })
        }, 2000)
      },
      fail: function () {
        self.setData({ submitting: false })
        self.setData({
          errorVisible: true,
          errorTitle: '网络异常',
          errorMessage: '无法连接服务器，请重试'
        })
      }
    })
  },

  // ─── 扫码流程 ──────────────────────────────

  onScanTap: function () {
    if (this.data.state !== 'idle') return
    var self = this
    this.setData({ state: 'scanning' })

    wx.scanCode({
      scanType: ['qrCode'],
      success: function (scan) {
        self._handleScanResult(scan)
      },
      fail: function (err) {
        console.log('scanCode fail', err)
        self.setData({ state: 'idle' })
      }
    })
  },

  _handleScanResult: function (scan) {
    var raw = scan.result || ''
    var match = raw.match(/^ARK-P:(\d+):([a-f0-9]+)$/)
    if (!match) {
      this._showError('二维码无效', '请扫描正确的工艺流转卡二维码')
      this.setData({ state: 'idle' })
      return
    }

    var orderProductId = parseInt(match[1])
    var sign = match[2]
    var self = this

    this.setData({ state: 'validating', loading: true })

    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }

    wx.request({
      url: app.globalData.baseUrl + '/api/mini/scan/product/' + orderProductId + '?sign=' + sign,
      method: 'GET',
      header: header,
      timeout: 30000,
      success: function (res) {
        self.setData({ loading: false })
        if (res.statusCode === 401) {
          app.logout()
          return
        }
        if (res.statusCode >= 400) {
          self._showError('请求失败', '服务器返回错误 (' + res.statusCode + ')，请稍后重试')
          self.setData({ state: 'idle' })
          return
        }
        var info = res.data
        if (!info.can_submit) {
          self._showBlockError(info.block_reason, info.next_process)
          self.setData({ state: 'idle' })
          return
        }
        self.setData({
          state: 'showing-confirm',
          productInfo: info.product,
          nextProcess: info.next_process,
          allProcesses: info.all_processes || [],
          canSubmit: true
        })
        if (typeof self.getTabBar === 'function' && self.getTabBar()) {
          self.getTabBar().setData({ hide: true })
        }
      },
      fail: function (err) {
        self.setData({ loading: false })
        self._showError('网络异常', '无法连接服务器，请检查网络后重试')
        self.setData({ state: 'idle' })
      }
    })
  },

  // ─── 提交报工 ──────────────────────────────

  onConfirmSubmit: function () {
    if (this.data.state !== 'showing-confirm') return
    this.setData({ state: 'submitting', submitting: true, submittingText: '报工提交中' })

    var self = this
    var header = { 'Content-Type': 'application/json' }
    if (app.globalData.token) {
      header['Authorization'] = 'Bearer ' + app.globalData.token
    }

    wx.request({
      url: app.globalData.baseUrl + '/api/mini/scan/submit',
      method: 'POST',
      data: {
        progress_id: this.data.nextProcess.progress_id,
        order_product_id: this.data.productInfo.id
      },
      header: header,
      timeout: 30000,
      success: function (res) {
        self.setData({ submitting: false })
        if (res.statusCode === 401) {
          app.logout()
          return
        }
        if (res.statusCode >= 400) {
          var detail = (res.data && res.data.detail) || {}
          if (detail.code === 'ALREADY_SUBMITTED') {
            self._showError('提交冲突', '该工序刚刚已被他人完成，请重新扫码')
            self.setData({ state: 'idle', productInfo: null, nextProcess: null })
            if (typeof self.getTabBar === 'function' && self.getTabBar()) {
              self.getTabBar().setData({ hide: false })
            }
          } else {
            self._showError('提交失败', detail.message || '服务器处理异常，请稍后重试')
            self.setData({ state: 'showing-confirm' })
          }
          return
        }

        var result = res.data
        self.setData({
          state: 'idle',
          productInfo: null,
          nextProcess: null,
          canSubmit: false,
          allProcesses: [],
          successVisible: true,
          successTitle: '报工成功',
          successMessage: result.message || '报工成功'
        })
        if (typeof self.getTabBar === 'function' && self.getTabBar()) {
          self.getTabBar().setData({ hide: false })
        }
        self.loadTodayHistory()

        setTimeout(function () {
          self.setData({ successVisible: false })
          if (result.all_done) {
            self._showError('🎉 全部完成', '该产品所有工序已完成！')
          }
        }, 2500)
      },
      fail: function () {
        self.setData({ submitting: false })
        self._showError('提交失败', '网络异常，请重试')
        self.setData({ state: 'showing-confirm' })
      }
    })
  },

  onCancelConfirm: function () {
    this.setData({ state: 'idle', productInfo: null, nextProcess: null, canSubmit: false, allProcesses: [], submitting: false })
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ hide: false })
    }
  },

  onSuccessTap: function () {
    this.setData({ successVisible: false })
  },

  onErrorTap: function () {
    this.setData({ errorVisible: false })
  },

  // ─── 查看记录 ──────────────────────────────

  onHistoryTap: function () {
    wx.navigateTo({ url: '/pages/overview/overview' })
  },

  onAllRecordsTap: function () {
    wx.navigateTo({ url: '/pages/history/history' })
  },

  // ─── 错误处理 ──────────────────────────────

  _showBlockError: function (reason, processInfo) {
    var content = BLOCK_MESSAGES[reason] || '无法提交，请联系管理员'
    if (reason === 'PROCESS_ALREADY_DONE' && processInfo && processInfo.completed_by) {
      content += '\n完成人：' + processInfo.completed_by
    }
    this.setData({ errorVisible: true, errorTitle: '无法报工', errorMessage: content })
  },

  _showError: function (title, message) {
    this.setData({ errorVisible: true, errorTitle: title, errorMessage: message })
  }
})
