import { onBeforeUnmount, reactive, ref } from 'vue'
import { getAssetBlob } from '@/api/designImage'
import { createObjectUrlRegistry } from '../state'

export function useAssetObjectUrls({ fetchAsset = getAssetBlob, urlApi = URL } = {}) {
  const registry = createObjectUrlRegistry(urlApi)
  const objectUrls = reactive({})
  const batchToken = ref(0)

  function keyFor(assetId, thumbnail, download = false) {
    return `${assetId}:${download ? 'download' : thumbnail ? 'thumb' : 'full'}`
  }

  function revoke(key) {
    registry.revoke(key)
    delete objectUrls[key]
  }

  function revokeAll() {
    registry.revokeAll()
    for (const key of Object.keys(objectUrls)) delete objectUrls[key]
  }

  function beginBatch() {
    batchToken.value += 1
    revokeAll()
    return batchToken.value
  }

  async function load(assetId, { thumbnail = true, download = false, token = batchToken.value } = {}) {
    const key = keyFor(assetId, thumbnail, download)
    if (objectUrls[key]) return objectUrls[key]
    const response = await fetchAsset(assetId, { thumbnail, download })
    if (token !== batchToken.value) return null
    const url = registry.create(key, response.data)
    objectUrls[key] = url
    return url
  }

  function get(assetId, thumbnail = true, download = false) {
    return objectUrls[keyFor(assetId, thumbnail, download)] ?? null
  }

  function cleanup() {
    batchToken.value += 1
    revokeAll()
  }

  onBeforeUnmount(cleanup)

  return { batchToken, objectUrls, beginBatch, cleanup, get, load, revoke, revokeAll }
}
