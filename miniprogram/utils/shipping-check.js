// utils/shipping-check.js — 发货检验页的纯函数：扫码分类、视图态装饰、提交体组装。
// 页面（pages/shipping/check/check.js）require 复用，测试在 tests/shipping-check.test.js。
// 与 utils/domestic-routing.js 同一套 CommonJS 导出风格。

var SHIPPING_PREFIX = 'ARK-I:'

// 扫码结果分类：shipping=出库单码（原文直交后端验签，小程序不解析格式），
// domestic=内贸码（ARK-D/ARK-DU，提示换码），other=不认识的码，empty=没扫到内容。
function classifyScan(raw) {
  var text = typeof raw === 'string' ? raw.trim() : ''
  if (!text) return { kind: 'empty', raw: '' }
  if (text.indexOf(SHIPPING_PREFIX) === 0) return { kind: 'shipping', raw: text }
  if (text.indexOf('ARK-D:') === 0 || text.indexOf('ARK-DU:') === 0) {
    return { kind: 'domestic', raw: text }
  }
  return { kind: 'other', raw: text }
}

// 鉴权图片地址：GET /images/{file_path} 的 file_path 是路径参数，斜杠必须原样保留，
// 所以用 encodeURI（不编码 /）而不是 encodeURIComponent。
function imageUrl(baseUrl, filePath) {
  return baseUrl + '/api/mini/shipping-inspection/images/' + encodeURI(filePath)
}

// 整单/明细照片合计与提交门槛：整单含明细至少 1 张（前端预检，后端校验兜底），
// 已提交（submitted）后整页只读，不允许再传。
function photoStats(items, wholePhotos, submitted) {
  var total = (wholePhotos || []).length
  var list = items || []
  for (var i = 0; i < list.length; i++) total += (list[i].photos || []).length
  return { totalPhotos: total, canSubmit: !submitted && total > 0 }
}

// 扫码响应 → 视图态：照片按 item_id 分组（item_id 空 = 整单照片）。
// wxml 不放表达式，行内要用的 qtyText / specText 都在这里拼好。
// item_id 对不上任何明细的孤儿照片不挂到任何分组（后端数据一致时不会出现）。
function decorateView(payload) {
  payload = payload || {}
  var record = payload.record || {}
  var inspection = payload.inspection || null
  var submitted = !!(inspection && inspection.status === 'submitted')

  var whole = []
  var byItem = {}
  var photos = payload.photos || []
  for (var i = 0; i < photos.length; i++) {
    var p = photos[i]
    var view = {
      id: p.id,
      itemId: p.item_id === null || p.item_id === undefined ? null : p.item_id,
      filePath: p.file_path,
      url: ''      // 鉴权图片要 downloadFile 换本地临时路径，由页面回填
    }
    if (view.itemId === null) whole.push(view)
    else {
      if (!byItem[view.itemId]) byItem[view.itemId] = []
      byItem[view.itemId].push(view)
    }
  }

  var items = (payload.items || []).map(function (it) {
    var ps = byItem[it.item_id] || []
    return {
      item_id: it.item_id,
      product_name: it.product_name,
      qty: it.qty,
      unit: it.unit || '',
      spec: it.spec || '',
      sku: it.sku || '',
      qtyText: '' + (it.qty === null || it.qty === undefined ? 0 : it.qty) + (it.unit || ''),
      specText: [it.spec, it.sku].filter(Boolean).join(' · '),
      photos: ps,
      photoCount: ps.length
    }
  })

  var stats = photoStats(items, whole, submitted)
  return {
    record: {
      outbound_record_id: record.outbound_record_id,
      outbound_no: record.outbound_no || '',
      outbound_date: record.outbound_date || '',
      customer_name: record.customer_name || ''
    },
    items: items,
    wholePhotos: whole,
    submitted: submitted,
    statusText: submitted ? '已提交' : '待检验',
    totalPhotos: stats.totalPhotos,
    canSubmit: stats.canSubmit
  }
}

// 提交体：request_id 是幂等键（同一次提交重试复用），remark 允许空串。
function buildSubmitBody(outboundRecordId, requestId, remark) {
  if (!outboundRecordId) throw new Error('缺少出库单 ID')
  if (!requestId) throw new Error('缺少 request_id')
  return {
    outbound_record_id: outboundRecordId,
    request_id: requestId,
    remark: remark || ''
  }
}

module.exports = {
  classifyScan: classifyScan,
  imageUrl: imageUrl,
  photoStats: photoStats,
  decorateView: decorateView,
  buildSubmitBody: buildSubmitBody
}
