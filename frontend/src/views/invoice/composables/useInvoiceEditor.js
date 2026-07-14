import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  checkInvoiceNo,
  createInvoice,
  getCustomerContactDefaults,
  getCustomerRule,
  getInvoice,
  getInvoiceEntryOptions,
  getInvoiceProductOptions,
  matchInvoiceProduct,
  resolveInvoicePrice,
  searchInvoiceCustomerContacts,
  searchInvoiceCustomers,
  suggestInvoiceNo,
  updateInvoice,
  validateInvoice,
} from '@/api/invoice'
import { useAuthStore } from '@/stores/auth'

export const CURL_OPTIONS = ['Straight', 'Body Wave', 'Deep Wave', 'Loose Wave', 'Kinky Curly', 'Water Wave']

export function useInvoiceEditor({ onSaved } = {}) {
  const drawerVisible = ref(false)
  const customerLoading = ref(false)
  const customerOptions = ref([])
  const selectedCustomer = ref(null)
  const customerRule = ref(null)
  // 联系人维度筛选（与公司筛选联动：选公司收敛联系人，选联系人反向定位公司）
  const contactLoading = ref(false)
  const contactOptions = ref([])
  const selectedContact = ref(null)
  // 「仅显示私海客户」默认勾选；两个筛选各自独立控制
  const privateOnlyCompany = ref(true)
  const privateOnlyContact = ref(true)
  // false = 当前账号未绑定 OKKI，私海筛选无从判定（前端提示去绑定）
  const okkiBound = ref(true)
  const invoiceNoTaken = ref(false)
  const entryOptions = ref({ displays: [], models: [], colors: [], sizes: [], units: [] })

  const form = reactive(emptyForm())

  const formProductTotal = computed(() =>
    form.items.reduce((sum, line) => sum + Number(line.total_price || 0), 0))
  const formTotal = computed(() =>
    formProductTotal.value + Number(form.shipping_fee || 0) + Number(form.surcharge_amount || 0))
  const isProduction = computed(() => form.order_type === 'production')

  function emptyForm() {
    return {
      id: null,
      invoice_no: '',
      order_type: 'stock',
      customer_id: '',
      customer_name: '',
      contact_name: '',
      contact_phone: '',
      contact_email: '',
      delivery_address: '',
      sales_user_name: '',
      sales_phone: '',
      sales_email: '',
      invoice_date: new Date().toISOString().slice(0, 10),
      currency: 'USD',
      express_channel: '',
      shipping_fee: 0,
      surcharge_name: '',
      surcharge_amount: 0,
      payment_term: '',
      internal_payment_method: '',
      internal_discount: null,
      internal_accessory: null,
      internal_received: null,
      internal_balance: null,
      internal_shipping_type: '',
      okki_new_deal: 1,
      okki_free_shipping: 1,
      okki_first_return: 0,
      remark: '',
      items: [],
    }
  }

  // 小满标记的智能默认只在用户没碰过开关时生效；编辑既有单一律尊重存值
  const okkiFlagsTouched = reactive({ newDeal: false, freeShipping: false })

  function markOkkiFlagTouched(key) {
    okkiFlagsTouched[key] = true
  }

  watch(() => form.shipping_fee, fee => {
    if (okkiFlagsTouched.freeShipping) return
    form.okki_free_shipping = Number(fee || 0) > 0 ? 0 : 1
  })

  function normalizeLine(line = {}) {
    return {
      // 既有行 id 必须回传：后端靠它跨保存传承 OKKI 明细 unique_id（编辑重推不塌行）
      id: line.id || null,
      item_type: line.item_type || 'stock',
      product_id: line.product_id || null,
      sku_id: line.sku_id || null,
      custom_product_id: line.custom_product_id || null,
      product_name: line.product_name || '',
      product_display: line.product_display || '',
      net_weight_grams: line.net_weight_grams || '',
      curl: line.curl || '',
      model: line.model || '',
      color: line.color || '',
      length: line.length || '',
      quantity: Number(line.quantity || 1),
      standard_price: line.standard_price == null ? null : Number(line.standard_price),
      customer_price: line.customer_price == null ? null : Number(line.customer_price),
      color_type_source: line.color_type_source || '',
      price_per_piece: line.price_per_piece == null ? null : Number(line.price_per_piece),
      total_price: Number(line.total_price || 0),
      price_source: line.price_source || 'manual',
      options: { models: [], colors: [], sizes: [], units: [] },
      matching: false,
    }
  }

  // 竞态守卫（cerebrum 2026-05-26 loadMore/doSearch 同款教训）：
  // 快速切换客户或切换 drawer 时，先发后至的过期响应不得覆盖当前表单
  let contactFillSeq = 0
  let customerRuleSeq = 0
  let customerSearchSeq = 0
  let contactSearchSeq = 0
  let invoiceNoSeq = 0
  // 用户手输过发票号后，建议号不再覆盖
  let invoiceNoEdited = false

  function resetForm(data = emptyForm()) {
    contactFillSeq++
    customerRuleSeq++
    invoiceNoSeq++
    // 编辑既有单（有 id）：发票号视为已确认，建议号不覆盖
    invoiceNoEdited = Boolean(data.id)
    invoiceNoTaken.value = false
    // 编辑既有单（有 id）时开关视为已人工确认，智能默认不再覆盖
    okkiFlagsTouched.newDeal = Boolean(data.id)
    okkiFlagsTouched.freeShipping = Boolean(data.id)
    Object.assign(form, emptyForm(), {
      ...data,
      shipping_fee: Number(data.shipping_fee || 0),
      surcharge_amount: Number(data.surcharge_amount || 0),
      // 存量 NULL 标记（068 前老单）镜像服务端兜底口径，不要硬填 1 锁死错误值
      okki_new_deal: data.okki_new_deal ?? 1,
      okki_free_shipping: data.okki_free_shipping ?? (Number(data.shipping_fee || 0) > 0 ? 0 : 1),
      okki_first_return: data.okki_first_return ?? 0,
      items: (data.items || []).map(normalizeLine),
    })
    selectedCustomer.value = form.customer_id
      ? { company_id: form.customer_id, company_name: form.customer_name }
      : null
    selectedContact.value = null
    contactOptions.value = []
    customerRule.value = null
    if (form.customer_id) loadCustomerRule()
  }

  async function searchCustomers(keyword) {
    const seq = ++customerSearchSeq
    customerLoading.value = true
    try {
      const res = await searchInvoiceCustomers({
        keyword,
        private_only: privateOnlyCompany.value,
      })
      if (seq !== customerSearchSeq) return
      customerOptions.value = res.items || []
      if (typeof res.okki_bound === 'boolean') okkiBound.value = res.okki_bound
    } finally {
      if (seq === customerSearchSeq) customerLoading.value = false
    }
  }

  async function searchContacts(keyword) {
    const seq = ++contactSearchSeq
    contactLoading.value = true
    try {
      const res = await searchInvoiceCustomerContacts({
        keyword,
        // 已选公司则收敛到该客户名下（联动）；未选则全局按联系人名搜
        company_id: form.customer_id || undefined,
        private_only: privateOnlyContact.value,
      })
      if (seq !== contactSearchSeq) return
      contactOptions.value = res.items || []
      if (typeof res.okki_bound === 'boolean') okkiBound.value = res.okki_bound
    } finally {
      if (seq === contactSearchSeq) contactLoading.value = false
    }
  }

  // 勾选切换即刷新候选（保持当前下拉内容与勾选一致）
  watch(privateOnlyCompany, () => { searchCustomers('') })
  watch(privateOnlyContact, () => { searchContacts('') })

  async function loadCustomerRule() {
    const seq = ++customerRuleSeq
    try {
      const rule = form.customer_id ? await getCustomerRule(form.customer_id) : null
      if (seq === customerRuleSeq) customerRule.value = rule
    } catch {
      if (seq === customerRuleSeq) customerRule.value = null
    }
  }

  async function onCustomerChange(customer) {
    form.customer_id = customer?.company_id == null ? '' : String(customer.company_id)
    form.customer_name = customer?.company_name || ''
    // 联动：公司变了，已选联系人若不属于新公司即失效；候选收敛到新公司名下
    if (selectedContact.value && String(selectedContact.value.company_id) !== form.customer_id) {
      selectedContact.value = null
    }
    searchContacts('')
    await Promise.all([loadCustomerRule(), fillContactDefaults()])
    // 客户变化 → 客户价规则变化，所有明细价重算
    await Promise.all(form.items.map(line => refreshLinePrice(line)))
  }

  async function onContactChange(contact) {
    selectedContact.value = contact || null
    if (!contact) return // 清空联系人筛选不动已选客户
    const companyChanged = String(contact.company_id) !== form.customer_id
    if (companyChanged) {
      // 联动：选联系人反向定位其所属客户
      form.customer_id = String(contact.company_id)
      form.customer_name = contact.company_name || ''
      selectedCustomer.value = {
        company_id: contact.company_id,
        company_name: contact.company_name,
        country_name: contact.country_name,
      }
      await Promise.all([loadCustomerRule(), fillContactDefaults()])
    }
    // 选中联系人是明确意图：整体覆盖联系字段（覆盖快照回填；残留他人联系方式是错单风险）
    form.contact_name = contact.name || ''
    form.contact_phone = contact.tel || ''
    form.contact_email = contact.email || ''
    if (companyChanged) {
      await Promise.all(form.items.map(line => refreshLinePrice(line)))
    }
  }

  // 联系人/地址是客户属性：选客户后用该客户最近一张发票的快照整体覆盖（含清空），
  // 残留上一个客户的地址是错单风险
  async function fillContactDefaults() {
    const seq = ++contactFillSeq
    let defaults = {}
    if (form.customer_id) {
      try {
        defaults = await getCustomerContactDefaults(form.customer_id) || {}
      } catch {
        defaults = {} // 拦截器已统一提示，回填静默跳过
      }
    }
    if (seq !== contactFillSeq) return // 期间又切了客户/换了单据，丢弃过期响应
    form.contact_name = defaults.contact_name || ''
    form.contact_phone = defaults.contact_phone || ''
    form.contact_email = defaults.contact_email || ''
    form.delivery_address = defaults.delivery_address || ''
    // 「是否新成交」预判：该客户在小满无历史订单 → 新成交（用户碰过开关则不动）
    if (!okkiFlagsTouched.newDeal && typeof defaults.has_xiaoman_orders === 'boolean') {
      form.okki_new_deal = defaults.has_xiaoman_orders ? 0 : 1
    }
  }

  async function openCreate(orderType = 'stock') {
    resetForm()
    form.order_type = orderType
    // 业务员信息默认当前登录用户（可改）；后端 create 对空字段还有一层兜底
    const me = useAuthStore().user
    if (me) {
      form.sales_user_name = me.real_name || ''
      form.sales_phone = me.phone || ''
      form.sales_email = me.email || ''
    }
    addLine()
    drawerVisible.value = true
    searchCustomers('')
    searchContacts('')
    fetchSuggestedInvoiceNo()
    if (orderType === 'production') loadEntryOptions()
  }

  async function openEdit(id) {
    const data = await getInvoice(id)
    resetForm(data)
    drawerVisible.value = true
    searchCustomers('')
    searchContacts('')
    if (form.order_type === 'production') loadEntryOptions()
  }

  // ── 发票号 ──────────────────────────────────────────

  async function fetchSuggestedInvoiceNo() {
    const seq = ++invoiceNoSeq
    try {
      const res = await suggestInvoiceNo({ order_type: form.order_type })
      // 期间用户手输过 / 切换了单据则丢弃建议号
      if (seq === invoiceNoSeq && !invoiceNoEdited && !form.id) {
        form.invoice_no = res.invoice_no || ''
      }
    } catch {
      // 拦截器已统一提示；建议号取不到时留空，保存由后端按规则生成兜底
    }
  }

  function onInvoiceNoInput() {
    invoiceNoEdited = true
    invoiceNoTaken.value = false
  }

  async function onInvoiceNoBlur() {
    const no = (form.invoice_no || '').trim()
    if (!no) return
    const seq = invoiceNoSeq // 期间切换单据（resetForm 递增）则丢弃过期响应
    try {
      const res = await checkInvoiceNo({ invoice_no: no, exclude_id: form.id || undefined })
      if (seq !== invoiceNoSeq || (form.invoice_no || '').trim() !== no) return
      invoiceNoTaken.value = !res.available
      if (!res.available) ElMessage.warning(`发票号 ${no} 已存在，请更换`)
    } catch {
      // 拦截器已统一提示；保存时后端还有唯一校验兜底
    }
  }

  async function loadEntryOptions() {
    entryOptions.value = await getInvoiceEntryOptions()
  }

  function addLine() {
    const last = form.items[form.items.length - 1]
    if (last) {
      // 按上一行内容自动填充，用户只改变化的参数（改任一关键词会重新匹配/取价）
      // id 必须剥离：复制行是新行，带上旧 id 会让两行继承同一个 OKKI unique_id
      const { options, matching, id, ...data } = last
      form.items.push(normalizeLine({ ...data }))
    } else {
      form.items.push(normalizeLine({ quantity: 1, item_type: isProduction.value ? 'custom' : 'stock' }))
    }
  }

  function removeLine(index) {
    form.items.splice(index, 1)
  }

  // ── 库存单：四维级联 ────────────────────────────────

  async function loadLineOptions(row) {
    const res = await getInvoiceProductOptions({
      model: row.model || undefined,
      color: row.color || undefined,
      size: row.length || undefined,
      unit: row.net_weight_grams || undefined,
    })
    row.options = {
      models: res.models || [],
      colors: res.colors || [],
      sizes: res.sizes || [],
      units: res.units || [],
    }
  }

  async function onLineFilterChange(row) {
    row.product_id = null
    row.sku_id = null
    row.product_name = ''
    row.product_display = ''
    await loadLineOptions(row)
    if (row.model && row.color && row.length && row.net_weight_grams) {
      await matchLineProduct(row)
    }
  }

  async function matchLineProduct(row) {
    row.matching = true
    try {
      const res = await matchInvoiceProduct({
        model: row.model,
        color: row.color,
        size: row.length,
        unit: row.net_weight_grams,
      })
      if (!res.is_unique) {
        ElMessage.warning((res.matches || []).length ? '当前条件匹配到多个产品，请继续确认规格' : '当前条件未匹配到产品')
        return
      }
      const item = res.item
      row.product_id = item.product_id
      row.sku_id = item.sku_id
      row.product_name = item.product_name
      row.product_display = item.product_display
      await refreshLinePrice(row)
    } finally {
      row.matching = false
    }
  }

  // ── 生产单：自由录入 ────────────────────────────────

  async function onCustomFieldChange(row) {
    row.product_name = ''
    if (row.product_display && row.color && row.length && row.net_weight_grams) {
      await refreshLinePrice(row)
    }
  }

  // ── 双价 ────────────────────────────────────────────

  async function refreshLinePrice(row) {
    if (!row.product_display || !row.color || !row.length || !row.net_weight_grams) return
    const res = await resolveInvoicePrice({
      customer_id: form.customer_id || undefined,
      product_display: row.product_display,
      length: row.length,
      unit: row.net_weight_grams,
      color: row.color,
    })
    row.standard_price = res.standard_price == null ? null : Number(res.standard_price)
    row.customer_price = res.customer_price == null ? null : Number(res.customer_price)
    row.color_type_source = res.color_type_source || ''
    if (row.customer_price != null) {
      row.price_per_piece = row.customer_price
      row.price_source = 'customer_rule'
    } else {
      row.price_source = 'missing_std'
    }
    updateLineTotal(row)
  }

  function onPriceInput(row) {
    if (row.customer_price != null) {
      row.price_source = Number(row.price_per_piece) === row.customer_price ? 'customer_rule' : 'manual'
    }
    updateLineTotal(row)
  }

  function updateLineTotal(row) {
    // 与后端 Decimal ROUND_HALF_UP 口径对齐，避免浮点差 1 分
    row.total_price = Math.round(Number(row.quantity || 0) * Number(row.price_per_piece || 0) * 100) / 100
  }

  // ── 保存 ────────────────────────────────────────────

  function buildPayload() {
    return {
      // 空串传 null：新建时后端按规则生成，编辑时保持原号
      invoice_no: (form.invoice_no || '').trim() || null,
      order_type: form.order_type,
      customer_id: form.customer_id,
      customer_name: form.customer_name,
      contact_name: form.contact_name || null,
      contact_phone: form.contact_phone || null,
      contact_email: form.contact_email || null,
      delivery_address: form.delivery_address || null,
      sales_user_name: form.sales_user_name || null,
      sales_phone: form.sales_phone || null,
      sales_email: form.sales_email || null,
      invoice_date: form.invoice_date,
      currency: form.currency || 'USD',
      express_channel: form.express_channel || null,
      shipping_fee: Number(form.shipping_fee || 0),
      surcharge_name: form.surcharge_name || null,
      surcharge_amount: Number(form.surcharge_amount || 0),
      payment_term: form.payment_term || null,
      internal_payment_method: form.internal_payment_method || null,
      internal_discount: form.internal_discount,
      internal_accessory: form.internal_accessory,
      internal_received: form.internal_received,
      internal_balance: form.internal_balance,
      internal_shipping_type: form.internal_shipping_type || null,
      okki_new_deal: form.okki_new_deal ?? null,
      okki_free_shipping: form.okki_free_shipping ?? null,
      okki_first_return: form.okki_first_return ?? null,
      remark: form.remark,
      items: form.items.map(line => ({
        id: line.id || null,
        item_type: line.item_type,
        product_id: line.product_id,
        sku_id: line.sku_id,
        product_name: line.product_name,
        product_display: line.product_display,
        net_weight_grams: line.net_weight_grams,
        curl: line.curl || null,
        model: line.model || null,
        color: line.color,
        length: line.length,
        quantity: line.quantity,
        price_per_piece: line.price_per_piece,
        price_source: line.price_source || 'manual',
      })),
    }
  }

  async function saveDraft() {
    const saved = form.id
      ? await updateInvoice(form.id, buildPayload())
      : await createInvoice(buildPayload())
    resetForm(saved)
    ElMessage.success('发票已保存')
    onSaved?.()
  }

  async function saveAndValidate() {
    await saveDraft() // saveDraft 内已触发 onSaved 刷新列表
    const res = await validateInvoice(form.id)
    if (res.ok) {
      ElMessage.success('校验通过，可以同步小满')
    } else {
      showIssues(res.issues)
    }
  }

  function showIssues(issues = []) {
    const html = issues.map(i => `<p>${i.field}: ${i.message}</p>`).join('') || '校验未通过'
    ElMessageBox.alert(html, '同步前校验', { dangerouslyUseHTMLString: true, confirmButtonText: '知道了' })
  }

  return {
    drawerVisible,
    customerLoading,
    customerOptions,
    selectedCustomer,
    customerRule,
    contactLoading,
    contactOptions,
    selectedContact,
    privateOnlyCompany,
    privateOnlyContact,
    okkiBound,
    invoiceNoTaken,
    entryOptions,
    form,
    formProductTotal,
    formTotal,
    isProduction,
    searchCustomers,
    searchContacts,
    onCustomerChange,
    onContactChange,
    onInvoiceNoInput,
    onInvoiceNoBlur,
    openCreate,
    openEdit,
    addLine,
    removeLine,
    loadLineOptions,
    onLineFilterChange,
    onCustomFieldChange,
    onPriceInput,
    updateLineTotal,
    saveDraft,
    saveAndValidate,
    showIssues,
    markOkkiFlagTouched,
  }
}

// 客户下拉统一显示格式：company_name(country_name)，无国家时只显示名称
export function customerLabel(customer) {
  if (!customer) return ''
  return customer.country_name
    ? `${customer.company_name}(${customer.country_name})`
    : customer.company_name || ''
}

// 联系人下拉：姓名 — 所属公司（跨公司搜索时靠公司名区分同名联系人）
export function contactLabel(contact) {
  if (!contact) return ''
  const name = contact.name || ''
  return contact.company_name ? `${name} — ${contact.company_name}` : name
}

export function describeCustomerRule(rule) {
  if (!rule) return ''
  const sign = Number(rule.adjust_value) >= 0 ? '+' : ''
  return rule.adjust_type === 'percent'
    ? `标准价 ${sign}${Number(rule.adjust_value)}%`
    : `标准价 ${sign}${Number(rule.adjust_value)}`
}
