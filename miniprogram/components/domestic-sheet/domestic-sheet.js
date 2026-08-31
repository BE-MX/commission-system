// components/domestic-sheet/domestic-sheet.js
// 内贸报工确认弹层。结构照 confirm-sheet（外贸），多了数量与图文要求。
var routing = require('../../utils/domestic-routing')
Component({
  properties: {
    visible: { type: Boolean, value: false },
    item: { type: Object, value: {} },        // scan_item 返回的明细信息
    nextStep: { type: Object, value: {} },    // 该报的工序
    steps: { type: Array, value: [] },        // 全部工序（默认折叠，点进度条才看）
    images: { type: Array, value: [] },       // 参考图临时路径
    userName: { type: String, value: '' },
    submitting: { type: Boolean, value: false }
  },

  data: {
    qty: 1,        // 真值：按钮文案与提交都用它
    qtyText: '1',  // 输入框显示值：只在 ±/全部/失焦 时程序化改，打字期间不回写
    maxQty: 1,
    totalSteps: 0,
    progressPercent: 0,
    showTimeline: false,
    stepList: [],
    reqOpen: false,
    hasRequirement: false,
    isDecision: false,
    decisionOptions: [],
    outcomeValues: {},
    decisionTotal: 0,
    selectedOutcomeCode: ''
  },

  observers: {
    'nextStep': function (s) {
      if (!s) return
      var max = s.reportable_qty || 0
      var q = max > 0 ? max : 1
      var options = s.rule_type === 'decision' ? (s.outcome_options || []).map(function (option) {
        return { code: option.code, label: option.label, value: '' }
      }) : []
      var values = {}
      for (var i = 0; i < options.length; i++) values[options[i].code] = ''
      this.setData({
        maxQty: max, qty: q, qtyText: String(q),
        isDecision: s.rule_type === 'decision',
        decisionOptions: options,
        outcomeValues: values,
        decisionTotal: 0,
        selectedOutcomeCode: ''
      })   // 普通工序默认整批；分流工序必须现场选结果
    },
    'steps': function (list) {
      list = list || []
      var done = 0
      var view = list.map(function (s) {
        var progress = routing.decorateProgress(s)
        if (progress.done) done += 1
        return {
          progress_id: s.progress_id, step_order: s.step_order, process_name: s.process_name,
          completed_qty: progress.completedQty, skipped_qty: progress.skippedQty,
          passed_qty: progress.passedQty, order_qty: s.order_qty,
          last_reported_at: s.last_reported_at, pct: progress.percent, done: progress.done
        }
      })
      this.setData({
        stepList: view,
        totalSteps: list.length,
        progressPercent: list.length ? Math.round(done / list.length * 100) : 0
      })
    },
    'item': function (it) {
      it = it || {}
      this.setData({
        hasRequirement: Boolean(it.hairstyle || it.color || it.style_requirement || it.remark ||
          (it.hairstyle_images || []).length || (it.color_images || []).length ||
          (it.style_images || []).length || (it.remark_images || []).length)
      })
    },
    'visible': function (v) {
      if (!v) this.setData({ showTimeline: false, reqOpen: false })
    }
  },

  methods: {
    // catch 需要一个真实存在的方法名，空字符串（catchtap=""）挡不住冒泡
    noop: function () {},

    onOverlayTap: function (e) {
      // 只有真的点在遮罩本身才关闭。点弹层内部（尤其是数量输入框）时
      // e.target.id 是空的，直接返回——否则一点输入框整个弹层就被收掉。
      if (e && e.target && e.target.id !== 'dom-sheet-mask') return
      if (this.data.showTimeline) return
      if (!this.data.submitting) this.triggerEvent('cancel')
    },
    onCancel: function () {
      if (!this.data.submitting) this.triggerEvent('cancel')
    },
    onConfirm: function () {
      if (this.data.submitting) return
      if (this.data.isDecision) {
        var values = this.data.item && this.data.item.report_mode === 'unit'
          ? (this.data.selectedOutcomeCode ? this._unitOutcome(this.data.selectedOutcomeCode) : {})
          : this.data.outcomeValues
        try {
          var submission = routing.buildDecisionSubmission(
            this.data.decisionOptions, values, this.data.maxQty,
            this.data.item && this.data.item.report_mode
          )
          this.triggerEvent('confirm', submission)
        } catch (err) {
          this.triggerEvent('invalidqty', { maxQty: this.data.maxQty, message: err.message })
        }
        return
      }
      var q = this.data.item && this.data.item.report_mode === 'unit' ? 1 : this.data.qty
      if (!(q > 0) || q > this.data.maxQty) {
        this.triggerEvent('invalidqty', { maxQty: this.data.maxQty })
        return
      }
      this.triggerEvent('confirm', { qty: q })
    },
    _unitOutcome: function (code) {
      var values = {}
      values[code] = true
      return values
    },
    onDecisionInput: function (e) {
      var code = e.currentTarget.dataset.code
      var index = e.currentTarget.dataset.index
      var value = e.detail.value
      var key = 'outcomeValues.' + code
      var change = {}
      change[key] = value
      change['decisionOptions[' + index + '].value'] = value
      var total = 0
      var values = this.data.outcomeValues || {}
      for (var i = 0; i < this.data.decisionOptions.length; i++) {
        var optionCode = this.data.decisionOptions[i].code
        total += Number(optionCode === code ? value : values[optionCode]) || 0
      }
      change.decisionTotal = total
      this.setData(change)
    },
    onDecisionSelect: function (e) {
      this.setData({ selectedOutcomeCode: e.currentTarget.dataset.code, decisionTotal: 1 })
    },

    // ── 数量 ──
    _clamp: function (v) {
      if (!(v > 0)) return 1
      return v > this.data.maxQty ? this.data.maxQty : v
    },
    _setQty: function (v) {
      this.setData({ qty: v, qtyText: String(v) })
    },

    // 打字期间只更新真值，不回写 qtyText —— 回写会让「清空重填」变成清空即跳 0，
    // 用户根本删不掉原来的数字（2026-07-27 亮哥反馈「无法编辑」）
    onInput: function (e) {
      this.setData({ qty: parseInt(e.detail.value, 10) || 0 })
    },
    // 失焦/回车时才纠正越界并同步显示值
    onBlur: function () { this._setQty(this._clamp(this.data.qty)) },

    onMinus: function () { if (this.data.qty > 1) this._setQty(this.data.qty - 1) },
    onPlus: function () { if (this.data.qty < this.data.maxQty) this._setQty(this.data.qty + 1) },
    onAll: function () { this._setQty(this.data.maxQty) },

    // ── 折叠区 ──
    onToggleReq: function () { this.setData({ reqOpen: !this.data.reqOpen }) },
    onPreview: function (e) {
      var i = e.currentTarget.dataset.index
      wx.previewImage({ current: this.data.images[i], urls: this.data.images })
    },

    // ── 工序时间轴 ──
    onProgressTap: function () { this.setData({ showTimeline: true }) },
    onTimelineClose: function () { this.setData({ showTimeline: false }) },
    onTimelineMaskTap: function (e) {
      if (e && e.target && e.target.id !== 'dom-timeline-mask') return
      this.setData({ showTimeline: false })
    }
  }
})
