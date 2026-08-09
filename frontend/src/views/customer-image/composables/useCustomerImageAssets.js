import { onBeforeUnmount, reactive, ref } from 'vue'

export function createObjectUrlRegistry({
  createObjectURL = blob => URL.createObjectURL(blob),
  revokeObjectURL = url => URL.revokeObjectURL(url),
} = {}) {
  const urls = new Map()

  function release(url) {
    try { revokeObjectURL(url) } catch { /* Always forget stale browser resources. */ }
  }

  function remove(key) {
    const url = urls.get(key)
    if (!url) return
    urls.delete(key)
    release(url)
  }

  return {
    replace(key, blob) {
      const next = createObjectURL(blob)
      const previous = urls.get(key)
      urls.set(key, next)
      if (previous) release(previous)
      return next
    },
    get: key => urls.get(key) ?? null,
    remove,
    clear() {
      for (const key of [...urls.keys()]) remove(key)
    },
  }
}

export function assetIdFromResultUrl(url) {
  const match = /^\/api\/customer-image\/public\/assets\/(\d+)\/content$/.exec(url || '')
  return match ? Number(match[1]) : null
}

export function useCustomerImageAssets({
  fetchProductAsset,
  fetchInviteAsset,
  urlApi = URL,
} = {}) {
  const registry = createObjectUrlRegistry({
    createObjectURL: blob => urlApi.createObjectURL(blob),
    revokeObjectURL: url => urlApi.revokeObjectURL(url),
  })
  const coverUrls = reactive({})
  const generationUrls = reactive({})
  const logoUrl = ref('')
  let generation = 0

  async function replaceFromResponse(key, response) {
    return registry.replace(key, response.data)
  }

  async function loadProductCovers(products) {
    const token = ++generation
    await Promise.all((products || []).map(async product => {
      const cover = product.assets?.find(asset => asset.role === 'cover')
      if (!cover) return
      const response = await fetchProductAsset(product.id, cover.id)
      if (token !== generation) return
      coverUrls[product.id] = await replaceFromResponse(`product:${product.id}`, response)
    }))
  }

  async function loadLogo(asset) {
    if (!asset?.id) {
      registry.remove('logo')
      logoUrl.value = ''
      return ''
    }
    const response = await fetchInviteAsset(asset.id)
    logoUrl.value = await replaceFromResponse('logo', response)
    return logoUrl.value
  }

  async function loadGeneration(generationItem) {
    const assetId = assetIdFromResultUrl(generationItem?.result_url)
    if (!assetId) return null
    const key = `generation:${generationItem.id}`
    if (registry.get(key)) return registry.get(key)
    const response = await fetchInviteAsset(assetId)
    generationUrls[generationItem.id] = await replaceFromResponse(key, response)
    return generationUrls[generationItem.id]
  }

  async function loadGenerationResults(generations) {
    await Promise.all((generations || [])
      .filter(item => item.status === 'succeeded' && item.result_url)
      .map(loadGeneration))
  }

  function clear() {
    generation += 1
    registry.clear()
    logoUrl.value = ''
    for (const key of Object.keys(coverUrls)) delete coverUrls[key]
    for (const key of Object.keys(generationUrls)) delete generationUrls[key]
  }

  onBeforeUnmount(clear)
  return {
    coverUrls,
    generationUrls,
    logoUrl,
    loadGeneration,
    loadGenerationResults,
    loadLogo,
    loadProductCovers,
    clear,
  }
}
