// components/nav-bar/nav-bar.js
Component({
  properties: {
    title: { type: String, value: '' },
    showBack: { type: Boolean, value: false },
    rightText: { type: String, value: '' }
  },

  data: {
    statusBarHeight: 20
  },

  lifetimes: {
    attached: function () {
      var sysInfo = wx.getSystemInfoSync()
      this.setData({ statusBarHeight: sysInfo.statusBarHeight || 20 })
    }
  },

  methods: {
    onBack: function () {
      wx.navigateBack({ delta: 1 })
    }
  }
})
