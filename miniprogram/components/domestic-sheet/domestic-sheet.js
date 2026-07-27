// components/domestic-sheet/domestic-sheet.js
// 内贸报工确认弹层。结构照 confirm-sheet（外贸），多了数量与图文要求。
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
    qty: 1,
    maxQty: 1,
    totalSteps: 0,
    progressPercent: 0,
    showTimeline: false,
    stepList: [],
    reqOpen: false,
    hasRequirement: false
  },

  observers: {
    'nextStep': function (s) {
      if (!s) return
      var max = s.reportable_qty || 0
      this.setData({ maxQty: max, qty: max > 0 ? max : 1 })   // 默认整批，改小即拆批
    },
    'steps': function (list) {
      list = list || []
      var done = 0
      var view = list.map(function (s) {
        var pct = s.order_qty ? Math.round(s.completed_qty / s.order_qty * 100) : 0
        var finished = s.completed_qty >= s.order_qty && s.order_qty > 0
        if (finished) done += 1
        return {
          progress_id: s.progress_id, step_order: s.step_order, process_name: s.process_name,
          completed_qty: s.completed_qty, order_qty: s.order_qty,
          last_reported_at: s.last_reported_at, pct: pct, done: finished
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
    onOverlayTap: function () {
      if (this.data.showTimeline) return
      if (!this.data.submitting) this.triggerEvent('cancel')
    },
    onCancel: function () {
      if (!this.data.submitting) this.triggerEvent('cancel')
    },
    onConfirm: function () {
      if (this.data.submitting) return
      var q = this.data.qty
      if (!(q > 0) || q > this.data.maxQty) {
        this.triggerEvent('invalidqty', { maxQty: this.data.maxQty })
        return
      }
      this.triggerEvent('confirm', { qty: q })
    },

    // ── 数量 ──
    _clamp: function (v) {
      if (!(v > 0)) return 1
      return v > this.data.maxQty ? this.data.maxQty : v
    },
    onInput: function (e) { this.setData({ qty: parseInt(e.detail.value) || 0 }) },
    onBlur: function () { this.setData({ qty: this._clamp(this.data.qty) }) },
    onMinus: function () { if (this.data.qty > 1) this.setData({ qty: this.data.qty - 1 }) },
    onPlus: function () { if (this.data.qty < this.data.maxQty) this.setData({ qty: this.data.qty + 1 }) },
    onAll: function () { this.setData({ qty: this.data.maxQty }) },

    // ── 折叠区 ──
    onToggleReq: function () { this.setData({ reqOpen: !this.data.reqOpen }) },
    onPreview: function (e) {
      var i = e.currentTarget.dataset.index
      wx.previewImage({ current: this.data.images[i], urls: this.data.images })
    },

    // ── 工序时间轴 ──
    onProgressTap: function () { this.setData({ showTimeline: true }) },
    onTimelineClose: function () { this.setData({ showTimeline: false }) },
    onTimelineMaskTap: function () { this.setData({ showTimeline: false }) }
  }
})
