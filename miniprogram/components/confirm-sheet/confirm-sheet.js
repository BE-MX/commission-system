// components/confirm-sheet/confirm-sheet.js
Component({
  properties: {
    visible: { type: Boolean, value: false },
    productInfo: { type: Object, value: {} },
    nextProcess: { type: Object, value: {} },
    allProcesses: { type: Array, value: [] },
    userName: { type: String, value: '' },
    submitting: { type: Boolean, value: false }
  },

  data: {
    progressPercent: 0,
    showTimeline: false,
    processList: []
  },

  observers: {
    'nextProcess': function (np) {
      if (np && np.step_order && np.total_steps) {
        this.setData({ progressPercent: Math.round((np.step_order / np.total_steps) * 100) })
      }
    },
    'allProcesses': function (list) {
      console.log('[confirm-sheet] allProcesses observer fired, length:', (list && list.length) || 0)
      if (list && list.length) {
        console.log('[confirm-sheet] first item:', JSON.stringify(list[0]))
      }
      this.setData({ processList: list || [] })
    },
    'visible': function (v) {
      if (!v && this.data.showTimeline) {
        this.setData({ showTimeline: false })
      }
    }
  },

  methods: {
    onOverlayTap: function () {
      if (this.data.showTimeline) return
      if (!this.data.submitting) {
        this.triggerEvent('cancel')
      }
    },

    onCancel: function () {
      if (!this.data.submitting) {
        this.triggerEvent('cancel')
      }
    },
    onConfirm: function () {
      if (!this.data.submitting) {
        this.triggerEvent('confirm')
      }
    },

    onProgressTap: function () {
      var list = this.properties.allProcesses || this.data.processList || []
      console.log('[confirm-sheet] onProgressTap')
      console.log('[confirm-sheet] properties.allProcesses length:', (this.properties.allProcesses || []).length)
      console.log('[confirm-sheet] data.processList length:', this.data.processList.length)
      console.log('[confirm-sheet] using list length:', list.length)
      // 强制同步到 data
      this.setData({
        processList: list,
        showTimeline: true
      })
    },

    onTimelineClose: function () {
      this.setData({ showTimeline: false })
    },

    onTimelineMaskTap: function () {
      this.setData({ showTimeline: false })
    }
  }
})
