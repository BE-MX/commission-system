import { ref } from 'vue'
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
  const urls = ref({})
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
    pending.delete(productId)
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
      const request = (async () => {
        const response = await fetchCover(productId)
        if (disposed || versions.get(productId) !== version || desired.get(productId) !== assetId) return
        const url = urlApi.createObjectURL(response.data)
        entries.set(productId, { assetId, url })
        urls.value = { ...urls.value, [productId]: url }
      })()
      const activeRequest = { assetId, promise: request }
      pending.set(productId, activeRequest)
      requests.push(request.finally(() => {
        if (pending.get(productId) === activeRequest) pending.delete(productId)
      }))
    }
    await Promise.all(requests)
  }

  function dispose() {
    disposed = true
    for (const productId of new Set([...desired.keys(), ...entries.keys(), ...pending.keys()])) {
      invalidate(productId)
      release(productId)
    }
    desired.clear()
  }

  return { urls, sync, dispose }
}

export function createAssetBlobController({ fetchBlob, urlApi = URL } = {}) {
  const urls = ref({})
  let epoch = 0
  let activeController = null
  let disposed = false

  function releaseAll() {
    for (const url of Object.values(urls.value)) urlApi.revokeObjectURL(url)
    urls.value = {}
  }

  function invalidate() {
    epoch += 1
    activeController?.abort()
    activeController = null
    releaseAll()
  }

  async function load(items) {
    if (disposed) return urls.value
    invalidate()
    const requestEpoch = epoch
    const controller = new AbortController()
    activeController = controller
    try {
      const blobs = await Promise.all((items || []).map(async item => {
        const response = await fetchBlob(item, { signal: controller.signal })
        return [item.id, response.data]
      }))
      if (disposed || epoch !== requestEpoch || controller.signal.aborted) return urls.value
      const next = {}
      for (const [id, blob] of blobs) next[id] = urlApi.createObjectURL(blob)
      urls.value = next
      return urls.value
    } catch (error) {
      if (disposed || epoch !== requestEpoch || controller.signal.aborted) return urls.value
      throw error
    } finally {
      if (activeController === controller) activeController = null
    }
  }

  function dispose() {
    disposed = true
    invalidate()
  }

  return { urls, load, invalidate, dispose }
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
  now = () => new Date(),
} = {}) {
  const products = ref([])
  const customers = ref([])
  const invites = ref([])
  const generations = ref([])
  const invitePage = ref(1)
  const invitePageSize = ref(20)
  const inviteTotal = ref(0)
  const generationPage = ref(1)
  const generationPageSize = ref(20)
  const generationTotal = ref(0)
  const oneTimeInviteUrl = ref('')
  const productCovers = createProductCoverController({ fetchCover: api.getProductCoverBlob })
  const requestVersions = { customers: 0, products: 0, invites: 0, generations: 0 }

  async function loadProducts() {
    const version = ++requestVersions.products
    const response = await api.listProducts()
    if (version !== requestVersions.products) return products.value
    products.value = response.data || []
    await productCovers.sync(products.value)
    return products.value
  }

  async function searchScopedCustomers(search) {
    const version = ++requestVersions.customers
    const term = String(search || '').trim()
    if (!term) {
      customers.value = []
      return []
    }
    const response = await api.searchCustomers({ search: term })
    if (version !== requestVersions.customers) return customers.value
    customers.value = response.data || []
    return customers.value
  }

  async function loadInvites(page = invitePage.value, pageSize = invitePageSize.value, requestConfig = {}) {
    const version = ++requestVersions.invites
    const response = await api.listInvites({ page, page_size: pageSize }, requestConfig)
    if (version !== requestVersions.invites) return invites.value
    const data = response.data || {}
    invites.value = data.items || []
    invitePage.value = data.page || page
    invitePageSize.value = data.page_size || pageSize
    inviteTotal.value = data.total || 0
    return invites.value
  }

  async function loadGenerations(page = generationPage.value, pageSize = generationPageSize.value) {
    const version = ++requestVersions.generations
    const response = await api.listGenerations({ page, page_size: pageSize })
    if (version !== requestVersions.generations) return generations.value
    const data = response.data || {}
    generations.value = data.items || []
    generationPage.value = data.page || page
    generationPageSize.value = data.page_size || pageSize
    generationTotal.value = data.total || 0
    return generations.value
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
    const response = await api.createInvite(payload)
    oneTimeInviteUrl.value = response.data?.invite_url || ''
    try {
      await loadInvites(1, invitePageSize.value, { suppressToast: true })
    } catch { /* The plaintext result must survive an independent list refresh failure. */ }
    return response.data
  }

  async function copyOneTimeInviteUrl() {
    if (!oneTimeInviteUrl.value || !clipboard?.writeText) return false
    try {
      await clipboard.writeText(oneTimeInviteUrl.value)
      return true
    } catch {
      return false
    }
  }

  function clearOneTimeInviteUrl() {
    oneTimeInviteUrl.value = ''
  }

  async function revokeInvite(inviteId) {
    const response = await api.revokeInvite(inviteId)
    const index = invites.value.findIndex(item => item.id === inviteId)
    if (index >= 0) invites.value[index] = response.data
    return response.data
  }

  async function saveProduct(product) {
    const draft = cloneProduct(product)
    const error = validateProductDraft(draft)
    if (error) throw new Error(error)
    const payload = productPayload(draft)
    const response = draft.id
      ? await api.updateProduct(draft.id, payload)
      : await api.createProduct(payload)
    const index = products.value.findIndex(item => item.id === response.data.id)
    if (index >= 0) products.value[index] = response.data
    else products.value = [...products.value, response.data]
    await productCovers.sync(products.value)
    return response.data
  }

  async function removeProduct(productId) {
    await api.deleteProduct(productId)
    products.value = products.value.filter(item => item.id !== productId)
    await productCovers.sync(products.value)
  }

  async function setProductPublished(productId, published) {
    const response = published
      ? await api.publishProduct(productId)
      : await api.unpublishProduct(productId)
    const index = products.value.findIndex(item => item.id === productId)
    if (index >= 0) products.value[index] = response.data
    await productCovers.sync(products.value)
    return response.data
  }

  return {
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
    dispose: productCovers.dispose,
  }
}
