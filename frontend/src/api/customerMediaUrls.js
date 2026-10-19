// 内部签名地址随素材 API 的部署位置解析，支持同源代理与云端直传。
const MEDIA_URL_FIELDS = ['content_url', 'playback_url', 'poster_url']

export function resolveBatchMediaUrls(data, apiBase, pageOrigin) {
  const origin = new URL(apiBase, pageOrigin).origin
  const batches = Array.isArray(data) ? data : data?.batches || [data]
  for (const batch of batches) {
    for (const asset of batch?.assets || []) {
      for (const field of MEDIA_URL_FIELDS) {
        if (asset[field]?.startsWith('/api/customer-media/')) {
          asset[field] = new URL(asset[field], origin).href
        }
      }
    }
  }
  return data
}
