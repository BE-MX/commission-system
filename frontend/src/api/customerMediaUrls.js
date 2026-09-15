// 内部签名地址随素材 API 的部署位置解析，支持同源代理与云端直传。
export function resolveBatchMediaUrls(data, apiBase, pageOrigin) {
  const origin = new URL(apiBase, pageOrigin).origin
  const batches = Array.isArray(data) ? data : data?.batches || [data]
  for (const batch of batches) {
    for (const asset of batch?.assets || []) {
      if (asset.content_url?.startsWith('/api/customer-media/')) {
        asset.content_url = new URL(asset.content_url, origin).href
      }
    }
  }
  return data
}
