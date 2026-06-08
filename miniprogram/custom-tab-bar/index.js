// custom-tab-bar/index.js
Component({
  data: {
    selected: 0,
    hide: false
  },

  methods: {
    onTabTap: function (e) {
      var index = e.currentTarget.dataset.index
      var urls = [
        '/pages/scan/scan',
        '/pages/photo/photo',
        '/pages/assistant/assistant'
      ]
      wx.switchTab({ url: urls[index] })
    }
  }
})
