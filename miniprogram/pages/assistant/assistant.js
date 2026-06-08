// pages/assistant/assistant.js — 零 import

var recorderManager = wx.getRecorderManager()
var app = getApp()

Page({
  data: {
    statusBarHeight: 20,
    avatarLetter: '',
    messages: [],
    inputText: '',
    isRecording: false,
    isSending: false,
    scrollTarget: ''
  },

  onLoad: function () {
    var sysInfo = wx.getSystemInfoSync()
    var user = app.globalData.userInfo
    this.setData({
      statusBarHeight: sysInfo.statusBarHeight || 20,
      avatarLetter: user ? (user.name || '?').charAt(0) : '?'
    })
    this._initRecorder()

    var name = (app.globalData.userInfo && app.globalData.userInfo.name) || ''
    this.setData({
      messages: [{
        type: 'system',
        text: '你好' + (name ? ' ' + name : '') + '，我是 leShine 生产助手。可以向我查询订单进度、报工记录，或语音发送指令。'
      }]
    })
  },

  onShow: function () {
    if (typeof this.getTabBar === 'function' && this.getTabBar()) {
      this.getTabBar().setData({ selected: 2 })
    }
  },

  _initRecorder: function () {
    var self = this
    recorderManager.onStop(function (res) {
      if (!res.tempFilePath) return
      self.setData({ isRecording: false })
      wx.showLoading({ title: '识别中...', mask: true })

      wx.uploadFile({
        url: app.globalData.baseUrl + '/api/mini/voice/transcribe',
        filePath: res.tempFilePath,
        name: 'audio',
        header: { 'Authorization': 'Bearer ' + app.globalData.token },
        success: function (uploadRes) {
          wx.hideLoading()
          try {
            var data = JSON.parse(uploadRes.data)
            if (data.text) {
              self.setData({ inputText: data.text })
              wx.vibrateShort({ type: 'light' })
            }
          } catch (e) {
            wx.showToast({ title: '识别失败，请重试', icon: 'error' })
          }
        },
        fail: function () {
          wx.hideLoading()
          wx.showToast({ title: '上传失败，请重试', icon: 'error' })
        }
      })
    })

    recorderManager.onError(function () {
      self.setData({ isRecording: false })
      wx.showToast({ title: '录音失败', icon: 'error' })
    })
  },

  onVoiceStart: function () {
    var self = this
    wx.authorize({
      scope: 'scope.record',
      success: function () {
        self.setData({ isRecording: true })
        recorderManager.start({
          duration: 60000,
          format: 'mp3',
          sampleRate: 16000,
          numberOfChannels: 1,
          encodeBitRate: 64000
        })
        wx.vibrateShort({ type: 'medium' })
      },
      fail: function () {
        wx.showModal({
          title: '需要录音权限',
          content: '请在设置中允许使用麦克风',
          confirmText: '去设置',
          success: function (res) { if (res.confirm) wx.openSetting() }
        })
      }
    })
  },

  onVoiceStop: function () {
    if (!this.data.isRecording) return
    this.setData({ isRecording: false })
    recorderManager.stop()
  },

  onVoiceMove: function () {},

  onInputChange: function (e) {
    this.setData({ inputText: e.detail.value })
  },

  onSend: function () {
    var text = this.data.inputText.trim()
    if (!text || this.data.isSending) return

    var now = new Date()
    var h = now.getHours().toString()
    var m = now.getMinutes().toString()
    if (m.length < 2) m = '0' + m
    var timeStr = h + ':' + m

    var userMsg = { type: 'user', text: text, time: timeStr }
    var msgs = this.data.messages.concat([userMsg])
    this.setData({
      messages: msgs,
      inputText: '',
      isSending: true,
      scrollTarget: 'msg-' + (msgs.length - 1)
    })

    var self = this
    setTimeout(function () {
      var sysMsg = { type: 'system', text: '已收到您的消息，功能正在开发中...' }
      var newMsgs = self.data.messages.concat([sysMsg])
      self.setData({
        messages: newMsgs,
        isSending: false,
        scrollTarget: 'msg-' + (newMsgs.length - 1)
      })
    }, 800)
  }
})
