// One registry for the workbench and tab navigation. Unknown capabilities stay hidden.
var ENTRIES = [
  { id: 'export', name: '外贸报工', description: '扫码报工 · 整单流转', theme: 'export', logo: '/assets/logo-gold.png', url: '/pages/scan/scan', tab: true },
  { id: 'domestic', name: '内贸报工', description: '扫码报工 · 按量流转', theme: 'domestic', logo: '/assets/logo-green.png', url: '/pages/domestic/scan/scan', tab: true },
  { id: 'lookup', name: '订单速查', description: '扫码或单号查询进度', theme: 'lookup', url: '/pages/domestic/lookup/lookup' },
  { id: 'shipping', name: '出库检验', description: '扫码验货 · 拍照留档', theme: 'shipping', url: '/pages/shipping/check/check' }
]
function visibleEntries(allowed) {
  return ENTRIES.filter(function (entry) { return Array.isArray(allowed) && allowed.indexOf(entry.id) >= 0 })
}
function canAccess(id) {
  var data = getApp().globalData
  return !!data.token && visibleEntries(data.allowedEntries).some(function (entry) { return entry.id === id })
}
function guard(id) {
  if (canAccess(id)) return true
  wx.reLaunch({ url: getApp().globalData.token ? '/pages/entry/entry' : '/pages/login/login' })
  return false
}
function open(id) {
  if (!guard(id)) return
  var entry = visibleEntries(getApp().globalData.allowedEntries).find(function (item) { return item.id === id })
  wx[entry.tab ? 'switchTab' : 'navigateTo']({ url: entry.url })
}
module.exports = { visibleEntries: visibleEntries, canAccess: canAccess, guard: guard, open: open }
