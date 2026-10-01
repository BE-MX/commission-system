import { ref } from 'vue'
import { useAsyncResource } from '../../../../composables/useAsyncResource.js'
import { useListPage } from '../../../../composables/useListPage.js'
import { clearListResource } from '../../../../composables/useListResourceScope.js'
import { parseApiDateTime } from '../../../../utils/datetime.js'

export function customerOptionLabel(customer) {
  const name = String(customer?.name || '').trim() || '未知客户'
  const country = String(customer?.country || '').trim() || '未知国家'
  return `${name} · ${country}`
}

export function customerImageAdminCapabilities(hasPermission) {
  const canAdmin = hasPermission('customer_image:admin')
  return {
    canAdmin,
    canRead: canAdmin || hasPermission('customer_image:read'),
    canWrite: hasPermission('customer_image:write'),
  }
}

export function createEmptyProductDraft() {
  return {
    id: null,
    name: '',
    category: '',
    description: '',
    fixed_prompt: '',
    output_prompt: '',
    sort: 0,
    options: [],
  }
}

export function createEmptyOption(controlType = 'single_choice', sort = 0) {
  if (controlType === 'boolean') {
    return {
      key: '', label: '', control_type: 'boolean', required: true,
      default_value: 'true', sort,
      values: [
        { value: 'true', label: '是', prompt_fragment: '', sort: 0, is_active: true },
        { value: 'false', label: '否', prompt_fragment: '', sort: 1, is_active: true },
      ],
    }
  }
  return {
    key: '', label: '', control_type: controlType, required: true,
    default_value: '', sort, values: [],
  }
}

export function createEmptyOptionValue(sort = 0) {
  return {
    value: '', label: '', prompt_fragment: '', color_hex: null,
    pantone_code: null, sort, is_active: true,
  }
}

export function validateInviteDraft(draft, now = new Date()) {
  if (!String(draft?.customer_id || '').trim()) return '请选择客户'
  if (!draft?.expires_at) return '请明确设置失效时间'
  const expiresAt = parseApiDateTime(draft.expires_at)
  if (!expiresAt || expiresAt <= now) return '失效时间必须设置在未来'
  if (!Number.isInteger(draft?.quota_total) || draft.quota_total <= 0) return '生成额度必须是正整数'
  if (!Array.isArray(draft?.product_ids) || draft.product_ids.length === 0) return '请至少选择一个产品'
  return ''
}

export function inviteSubmissionErrorMessage(error) {
  const status = error?.response?.status
  const detail = error?.response?.data?.detail
  const knownDetails = {
    'customer not found': '所选客户已失效，请重新搜索并选择客户',
    'customer owner not found': '该客户缺少当前负责人，请联系管理员补全客户归属后重试',
    'published product not found': '所选产品已下架或不可用，请刷新页面后重新选择产品',
    'Not Found': '系统接口未加载，请刷新页面；若仍失败，请联系管理员重启后端服务',
  }
  if (typeof detail === 'string' && knownDetails[detail]) return knownDetails[detail]
  if (status === 404) return '客户或产品已失效，请刷新页面后重新选择'
  if (status === 409) return '客户或产品状态已变化，请刷新页面后重试'
  if (status === 503) return '服务暂时不可用，请稍后重试'
  if (!error?.response) return '网络连接失败，请检查网络后重试'
  return '邀请链接生成失败，请稍后重试；若仍失败，请联系管理员'
}

export function validateProductDraft(draft) {
  if (!String(draft?.name || '').trim()) return '请填写产品名称'
  if (!String(draft?.category || '').trim()) return '请填写产品分类'
  if (!String(draft?.fixed_prompt || '').trim()) return '请填写固定提示词'
  if (!String(draft?.output_prompt || '').trim()) return '请填写输出提示词'
  const keys = new Set()
  for (const option of draft.options || []) {
    if (!/^[a-z][a-z0-9_]*$/.test(option.key || '')) return '参数键须使用小写英文、数字或下划线'
    if (keys.has(option.key)) return '参数键不能重复'
    keys.add(option.key)
    if (!String(option.label || '').trim()) return '请填写参数名称'
    if (!['single_choice', 'color', 'boolean'].includes(option.control_type)) return '参数控件类型无效'
    if (!option.values?.length) return `参数“${option.label}”至少需要一个选项值`
    const activeValues = new Set()
    for (const value of option.values) {
      if (!String(value.value || '').trim() || !String(value.label || '').trim()) return `请补全“${option.label}”的选项值`
      if (!String(value.prompt_fragment || '').trim()) return `请填写“${value.label}”的提示词片段`
      if (option.control_type === 'color' && !/^#[0-9A-Fa-f]{6}$/.test(value.color_hex || '')) return `请为“${value.label}”填写标准色值`
      if (value.is_active !== false) activeValues.add(value.value)
    }
    if (option.required && !option.default_value) return `必填参数“${option.label}”需要默认值`
    if (option.default_value && !activeValues.has(option.default_value)) return `参数“${option.label}”的默认值必须启用`
  }
  return ''
}

export function validateProductForPublish(draft, assets) {
  const draftError = validateProductDraft(draft)
  if (draftError) return draftError
  if (!(assets || []).some(asset => asset.role === 'cover')) return '发布前必须上传封面图'
  if (!(assets || []).some(asset => asset.role === 'reference')) return '发布前必须上传参考图'
  return ''
}

export function moveReferenceIds(references, index, offset) {
  const ids = references.map(asset => asset.id)
  const target = index + offset
  if (target < 0 || target >= ids.length) return ids
  ;[ids[index], ids[target]] = [ids[target], ids[index]]
  return ids
}

export function createProductCoverController({ fetchCover, urlApi = URL } = {}) {
  const urls = ref({}), errors = ref({}), loading = ref({})
  const entries = new Map()
  const desired = new Map()
  const versions = new Map()
  const pending = new Map()
  let disposed = false

  function release(productId) {
    const entry = entries.get(productId)
    if (entry?.url) urlApi.revokeObjectURL(entry.url)
    entries.delete(productId)
    if (productId in urls.value) {
      const next = { ...urls.value }
      delete next[productId]
      urls.value = next
    }
  }

  function invalidate(productId) {
    versions.set(productId, (versions.get(productId) || 0) + 1)
    pending.get(productId)?.controller?.abort()
    pending.delete(productId)
    delete errors.value[productId]; delete loading.value[productId]
  }

  async function sync(products) {
    const nextDesired = new Map(
      (products || [])
        .filter(product => product.cover?.id)
        .map(product => [product.id, product.cover.id]),
    )
    for (const productId of new Set([...desired.keys(), ...entries.keys()])) {
      const nextAssetId = nextDesired.get(productId)
      if (!nextAssetId || desired.get(productId) !== nextAssetId) {
        invalidate(productId)
        release(productId)
      }
    }
    desired.clear()
    for (const [productId, assetId] of nextDesired) desired.set(productId, assetId)

    const requests = []
    for (const [productId, assetId] of desired) {
      if (entries.get(productId)?.assetId === assetId) continue
      const active = pending.get(productId)
      if (active?.assetId === assetId) {
        requests.push(active.promise)
        continue
      }
      const version = (versions.get(productId) || 0) + 1
      versions.set(productId, version)
      const controller = new AbortController()
      const isCurrent = () => !disposed && !controller.signal.aborted && versions.get(productId) === version && desired.get(productId) === assetId
      delete errors.value[productId]; loading.value[productId] = true
      const request = (async () => {
        try {
          const response = await fetchCover(productId, { signal: controller.signal, suppressToast: true })
          if (!isCurrent()) return
          const url = urlApi.createObjectURL(response.data)
          entries.set(productId, { assetId, url })
          urls.value = { ...urls.value, [productId]: url }
        } catch (error) {
          if (isCurrent()) errors.value[productId] = '封面读取失败，请重试'
        } finally { if (isCurrent()) loading.value[productId] = false }
      })()
      const activeRequest = { assetId, promise: request, controller }
      pending.set(productId, activeRequest)
      requests.push(request.finally(() => {
        if (pending.get(productId) === activeRequest) pending.delete(productId)
      }))
    }
    await Promise.all(requests)
  }

  function clear() {
    for (const productId of new Set([...desired.keys(), ...entries.keys(), ...pending.keys()])) {
      invalidate(productId)
      release(productId)
    }
    desired.clear()
  }

  function dispose() { disposed = true; clear() }
  return { urls, errors, loading, sync, clear, dispose }
}

export function createAssetBlobController({ fetchBlob, urlApi = URL } = {}) {
  const urls = ref({})
  const errors = ref({})
  const loading = ref({})
  const itemsById = new Map()
  const requests = new Map()
  let epoch = 0
  let disposed = false

  function invalidate() {
    epoch += 1
    for (const request of requests.values()) request.controller.abort()
    requests.clear()
    itemsById.clear()
    for (const url of Object.values(urls.value)) urlApi.revokeObjectURL(url)
    urls.value = {}
    errors.value = {}
    loading.value = {}
  }

  async function retry(id) {
    if (disposed || !itemsById.has(id)) return
    if (requests.has(id)) return requests.get(id).promise
    const item = itemsById.get(id)
    const requestEpoch = epoch
    const controller = new AbortController()
    const isCurrent = () => !disposed && epoch === requestEpoch && !controller.signal.aborted
    delete errors.value[id]
    loading.value[id] = true
    const request = { controller }
    requests.set(id, request)
    request.promise = (async () => {
      try {
        const response = await fetchBlob(item, { signal: controller.signal })
        if (!isCurrent()) return
        const url = urlApi.createObjectURL(response.data)
        if (urls.value[id]) urlApi.revokeObjectURL(urls.value[id])
        urls.value[id] = url
      } catch (error) {
        if (!isCurrent()) return
        errors.value[id] = error?.response?.status === 404
          ? '图片无法读取，请重试；仍失败可重新上传或联系管理员'
          : '图片加载失败，请检查网络后重试'
      } finally {
        if (isCurrent()) loading.value[id] = false
        if (requests.get(id) === request) requests.delete(id)
      }
    })()
    return request.promise
  }

  async function load(items) {
    if (disposed) return urls.value
    invalidate()
    for (const item of items || []) itemsById.set(item.id, item)
    await Promise.all([...itemsById.keys()].map(retry))
    return urls.value
  }

  function dispose() {
    disposed = true
    invalidate()
  }

  return { urls, errors, loading, load, retry, invalidate, dispose }
}

function cloneProduct(product) {
  return product ? JSON.parse(JSON.stringify(product)) : createEmptyProductDraft()
}

function productPayload(draft) {
  return {
    name: draft.name,
    category: draft.category,
    description: draft.description || null,
    fixed_prompt: draft.fixed_prompt,
    output_prompt: draft.output_prompt,
    sort: Number(draft.sort) || 0,
    options: (draft.options || []).map((option, optionIndex) => ({
      key: option.key,
      label: option.label,
      control_type: option.control_type,
      required: Boolean(option.required),
      default_value: option.default_value || null,
      sort: optionIndex,
      values: (option.values || []).map((value, valueIndex) => ({
        value: value.value,
        label: value.label,
        prompt_fragment: value.prompt_fragment,
        color_hex: option.control_type === 'color' ? value.color_hex : null,
        pantone_code: option.control_type === 'color' ? (value.pantone_code || null) : null,
        sort: valueIndex,
        is_active: value.is_active !== false,
      })),
    })),
  }
}

export function createCustomerImageAdminState({
  api,
  clipboard = globalThis.navigator?.clipboard,
  documentRef = globalThis.document,
  now = () => new Date(),
} = {}) {
  const productsResource = useAsyncResource(async (_, { signal }) => (await api.listProducts({}, { signal, suppressToast: true })).data || [], { initialData: [] })
  const customersResource = useAsyncResource(async (term, { signal }) => term ? (await api.searchCustomers({ search: term }, { signal, suppressToast: true })).data || [] : [], { initialData: [] })
  const invitesResource = useListPage(async (params, { signal }) => (await api.listInvites(params, { signal, suppressToast: true })).data || {}, { immediate: false })
  const generationsResource = useListPage(async (params, { signal }) => (await api.listGenerations(params, { signal, suppressToast: true })).data || {}, { immediate: false })
  const products = productsResource.data, customers = customersResource.data
  const invites = invitesResource.list, generations = generationsResource.list
  const invitePage = invitesResource.page, invitePageSize = invitesResource.pageSize, inviteTotal = invitesResource.total
  const generationPage = generationsResource.page, generationPageSize = generationsResource.pageSize, generationTotal = generationsResource.total
  const oneTimeInviteUrl = ref('')
  const productCovers = createProductCoverController({ fetchCover: api.getProductCoverBlob })
  const scopeVersion = ref(0)
  let customerScope = null
  async function loadProducts() {
    const success = await productsResource.load()
    if (success) await productCovers.sync(products.value)
    return success
  }
  function searchScopedCustomers(search) {
    const term = String(search || '').trim(), clear = term !== customerScope
    customerScope = term
    if (!term) { customersResource.clear(); return false }
    return customersResource.load(term, { clear })
  }
  function loadInvites(page = invitePage.value, pageSize = invitePageSize.value) {
    invitePage.value = page; invitePageSize.value = pageSize
    return invitesResource.fetchList()
  }
  function loadGenerations(page = generationPage.value, pageSize = generationPageSize.value) {
    generationPage.value = page; generationPageSize.value = pageSize
    return generationsResource.fetchList()
  }
  function clearScope() {
    scopeVersion.value++
    productsResource.clear(); customersResource.clear()
    clearListResource(invitesResource); clearListResource(generationsResource)
    productCovers.clear(); oneTimeInviteUrl.value = ''; customerScope = null
  }

  async function submitInvite(draft) {
    const error = validateInviteDraft(draft, now())
    if (error) throw new Error(error)
    const payload = {
      customer_id: String(draft.customer_id),
      product_ids: [...draft.product_ids],
      expires_at: parseApiDateTime(draft.expires_at).toISOString(),
      quota_total: Number(draft.quota_total),
    }
    const scope = scopeVersion.value
    const response = await api.createInvite(payload)
    if (scope !== scopeVersion.value) return response.data
    oneTimeInviteUrl.value = response.data?.invite_url || ''
    await invitesResource.refreshCreate()
    return response.data
  }

  async function copyOneTimeInviteUrl() {
    const text = oneTimeInviteUrl.value
    if (!text) return false
    if (clipboard?.writeText) {
      try {
        await clipboard.writeText(text)
        return true
      } catch { /* Some embedded browsers reject the Clipboard API at runtime. */ }
    }

    if (
      !documentRef?.body
      || typeof documentRef.createElement !== 'function'
      || typeof documentRef.execCommand !== 'function'
    ) return false

    const textarea = documentRef.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'fixed'
    textarea.style.top = '-9999px'
    textarea.style.opacity = '0'
    documentRef.body.appendChild(textarea)
    try {
      textarea.focus({ preventScroll: true })
      textarea.select()
      textarea.setSelectionRange?.(0, text.length)
      return Boolean(documentRef.execCommand('copy'))
    } catch {
      return false
    } finally {
      textarea.remove()
    }
  }

  function clearOneTimeInviteUrl() {
    oneTimeInviteUrl.value = ''
  }

  async function revokeInvite(inviteId) {
    const scope = scopeVersion.value
    const response = await api.revokeInvite(inviteId)
    if (scope !== scopeVersion.value) return response.data
    const index = invites.value.findIndex(item => item.id === inviteId)
    invitesResource.cancel()
    if (index >= 0) invites.value[index] = response.data
    return response.data
  }

  async function saveProduct(product) {
    const scope = scopeVersion.value
    const draft = cloneProduct(product)
    const error = validateProductDraft(draft)
    if (error) throw new Error(error)
    const payload = productPayload(draft)
    const response = draft.id
      ? await api.updateProduct(draft.id, payload)
      : await api.createProduct(payload)
    if (scope !== scopeVersion.value) return response.data
    const index = products.value.findIndex(item => item.id === response.data.id)
    if (index >= 0) products.value[index] = response.data
    else products.value = [...products.value, response.data]
    await productCovers.sync(products.value)
    await loadProducts()
    return response.data
  }

  async function removeProduct(productId) {
    const scope = scopeVersion.value
    await api.deleteProduct(productId)
    if (scope !== scopeVersion.value) return
    products.value = products.value.filter(item => item.id !== productId)
    await productCovers.sync(products.value)
    await loadProducts()
  }

  async function setProductPublished(productId, published) {
    const scope = scopeVersion.value
    const response = published
      ? await api.publishProduct(productId)
      : await api.unpublishProduct(productId)
    if (scope !== scopeVersion.value) return response.data
    const index = products.value.findIndex(item => item.id === productId)
    if (index >= 0) products.value[index] = response.data
    await productCovers.sync(products.value)
    await loadProducts()
    return response.data
  }

  return {
    productsResource, customersResource, invitesResource, generationsResource, scopeVersion, clearScope,
    products,
    customers,
    invites,
    generations,
    invitePage,
    invitePageSize,
    inviteTotal,
    generationPage,
    generationPageSize,
    generationTotal,
    productCoverUrls: productCovers.urls,
    productCoverErrors: productCovers.errors,
    productCoverLoading: productCovers.loading,
    retryProductCovers: () => productCovers.sync(products.value),
    oneTimeInviteUrl,
    loadProducts,
    searchScopedCustomers,
    loadInvites,
    loadGenerations,
    submitInvite,
    copyOneTimeInviteUrl,
    clearOneTimeInviteUrl,
    revokeInvite,
    saveProduct,
    removeProduct,
    setProductPublished,
    dispose: () => { clearScope(); productCovers.dispose() },
  }
}
