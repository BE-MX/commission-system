import { computed, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  createInvoice,
  getCustomerRule,
  getInvoice,
  getInvoiceEntryOptions,
  getInvoiceProductOptions,
  matchInvoiceProduct,
  resolveInvoicePrice,
  searchInvoiceCustomers,
  updateInvoice,
  validateInvoice,
} from '@/api/invoice'

export const CURL_OPTIONS = ['Straight', 'Body Wave', 'Deep Wave', 'Loose Wave', 'Kinky Curly', 'Water Wave']

export function useInvoiceEditor({ onSaved } = {}) {
  const drawerVisible = ref(false)
  const customerLoading = ref(false)
  const customerOptions = ref([])
  const selectedCustomer = ref(null)
  const customerRule = ref(null)
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
      remark: '',
      items: [],
    }
  }

  function normalizeLine(line = {}) {
    return {
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

  function resetForm(data = emptyForm()) {
    Object.assign(form, emptyForm(), {
      ...data,
      shipping_fee: Number(data.shipping_fee || 0),
      surcharge_amount: Number(data.surcharge_amount || 0),
      items: (data.items || []).map(normalizeLine),
    })
    selectedCustomer.value = form.customer_id
      ? { company_id: form.customer_id, company_name: form.customer_name }
      : null
    customerRule.value = null
    if (form.customer_id) loadCustomerRule()
  }

  async function searchCustomers(keyword) {
    customerLoading.value = true
    try {
      const res = await searchInvoiceCustomers({ keyword })
      customerOptions.value = res.items || []
    } finally {
      customerLoading.value = false
    }
  }

  async function loadCustomerRule() {
    try {
      customerRule.value = form.customer_id ? await getCustomerRule(form.customer_id) : null
    } catch {
      customerRule.value = null
    }
  }

  async function onCustomerChange(customer) {
    form.customer_id = customer?.company_id == null ? '' : String(customer.company_id)
    form.customer_name = customer?.company_name || ''
    await loadCustomerRule()
    // 客户变化 → 客户价规则变化，所有明细价重算
    await Promise.all(form.items.map(line => refreshLinePrice(line)))
  }

  async function openCreate(orderType = 'stock') {
    resetForm()
    form.order_type = orderType
    addLine()
    drawerVisible.value = true
    searchCustomers('')
    if (orderType === 'production') loadEntryOptions()
  }

  async function openEdit(id) {
    const data = await getInvoice(id)
    resetForm(data)
    drawerVisible.value = true
    if (form.order_type === 'production') loadEntryOptions()
  }

  async function loadEntryOptions() {
    entryOptions.value = await getInvoiceEntryOptions()
  }

  function addLine() {
    form.items.push(normalizeLine({ quantity: 1, item_type: isProduction.value ? 'custom' : 'stock' }))
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
      remark: form.remark,
      items: form.items.map(line => ({
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
    entryOptions,
    form,
    formProductTotal,
    formTotal,
    isProduction,
    searchCustomers,
    onCustomerChange,
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
  }
}

// 客户下拉统一显示格式：company_name(country_name)，无国家时只显示名称
export function customerLabel(customer) {
  if (!customer) return ''
  return customer.country_name
    ? `${customer.company_name}(${customer.country_name})`
    : customer.company_name || ''
}

export function describeCustomerRule(rule) {
  if (!rule) return ''
  const sign = Number(rule.adjust_value) >= 0 ? '+' : ''
  return rule.adjust_type === 'percent'
    ? `标准价 ${sign}${Number(rule.adjust_value)}%`
    : `标准价 ${sign}${Number(rule.adjust_value)}`
}
