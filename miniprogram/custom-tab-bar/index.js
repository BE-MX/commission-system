// custom-tab-bar/index.js
Component({
  data: {
    selected: 0,
    hide: false,
    // 拍照上传/生产助手功能未实现，正式版审核期间隐藏入口，功能就绪后改回 true
    showReserved: false
  },

  methods: {
    onTabTap: function (e) {
      var index = e.currentTarget.dataset.index
      // 顺序必须与 app.json tabBar.list、index.wxml 的 data-index、
      // 以及各页 onShow 里的 selected 三处完全一致（改一处要同时改四处）
      var urls = [
        '/pages/scan/scan',              // 0 外贸报工
        '/pages/domestic/scan/scan',     // 1 内贸报工
        '/pages/photo/photo',            // 2 拍照上传（未上线）
        '/pages/assistant/assistant'     // 3 生产助手（未上线）
      ]
      wx.switchTab({ url: urls[index] })
    }
  }
})
