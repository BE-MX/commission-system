// 小程序 Date 默认跟随手机时区；业务钟面时间统一按 UTC+8。
function beijingNow() {
  var local = new Date()
  return new Date(local.getTime() + (local.getTimezoneOffset() + 480) * 60000)
}

module.exports = { beijingNow: beijingNow }
