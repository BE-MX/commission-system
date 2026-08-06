import { onBeforeUnmount, reactive } from 'vue'
import { getLibraryAssetBlob } from '@/api/designImage'
import { createObjectUrlRegistry } from '../state'

/* 参考图库缩略图：blob + auth 头拉取后转 objectURL（<img> 不带 auth 头）。
   对话框关闭时整体 revoke，避免 Object URL 泄漏。 */
export function useLibraryObjectUrls({ fetchAsset = getLibraryAssetBlob, urlApi = URL } = {}) {
  const registry = createObjectUrlRegistry(urlApi)
  const objectUrls = reactive({})
  const pending = new Map()

  async function load(assetId) {
    if (objectUrls[assetId]) return objectUrls[assetId]
    if (pending.has(assetId)) return pending.get(assetId)
    const request = fetchAsset(assetId, { thumbnail: true })
      .then(response => {
        const url = registry.create(assetId, response.data)
        objectUrls[assetId] = url
        pending.delete(assetId)
        return url
      })
      .catch(error => {
        pending.delete(assetId)
        throw error
      })
    pending.set(assetId, request)
    return request
  }

  function get(assetId) {
    return objectUrls[assetId] ?? null
  }

  function revokeAll() {
    registry.revokeAll()
    for (const key of Object.keys(objectUrls)) delete objectUrls[key]
  }

  onBeforeUnmount(revokeAll)

  return { get, load, revokeAll }
}
