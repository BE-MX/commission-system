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
      var urls = [
        '/pages/scan/scan',
        '/pages/photo/photo',
        '/pages/assistant/assistant'
      ]
      wx.switchTab({ url: urls[index] })
    }
  }
})
