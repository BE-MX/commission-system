// custom-tab-bar/index.js
Component({
  data: {
    selected: 0,
    hide: false
  },

  methods: {
    onTabTap: function (e) {
      var index = e.currentTarget.dataset.index
      // 顺序必须与 app.json tabBar.list、index.wxml 的 data-index、
      // 以及各页 onShow 里的 selected 三处完全一致（改一处要同时改四处）
      var urls = [
        '/pages/scan/scan',              // 0 外贸报工
        '/pages/domestic/scan/scan'      // 1 内贸报工
      ]
      wx.switchTab({ url: urls[index] })
    }
  }
})
