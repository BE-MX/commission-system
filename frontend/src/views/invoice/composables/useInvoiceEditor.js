import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  checkInvoiceNo,
  createInvoice,
  getCustomerContactDefaults,
  getCustomerRule,
  getInvoice,
  searchInvoiceCustomerContacts,
  searchInvoiceCustomers,
  suggestInvoiceNo,
  updateInvoice,
} from '@/api/invoice'
import { validateThenSync } from './invoiceSyncFlow'
import { useAuthStore } from '@/stores/auth'
import {
  calculateBalance,
  calculateInvoiceTotal,
  computeHandlingFee,
  handlingFeeRate,
  normalizeDiscount,
  settlementMatchesTotal,
  sumLineNet,
} from './invoiceSettlement'
import { normalizeAccessoryRow } from './accessoryPricing'
import { useInvoiceAccessories } from './useInvoiceAccessories'
import { buildInvoicePayload, emptyInvoiceForm, normalizeHairRow } from './invoiceEditorState'
import { useInvoiceHairItems } from './useInvoiceHairItems'

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
  // 「仅显示私海客户」（2026-07-14 亮哥定版）：所有人默认私海；
  // invoice_private_filter:read 只控制勾选框显隐=能否切到全量视图。
  // 无权限用户勾选框隐藏、恒定私海——未绑定 OKKI 时唯一出路是去绑定（提示文案区分）
  const canTogglePrivate = computed(() => useAuthStore().hasPermission('invoice_private_filter:read'))
  const privateOnlyCompany = ref(true)
  const privateOnlyContact = ref(true)
  // false = 当前账号未绑定 OKKI，私海筛选无从判定（前端提示去绑定）
  const okkiBound = ref(true)
  const invoiceNoTaken = ref(false)
  const entryOptions = ref({ displays: [], models: [], colors: [], sizes: [], units: [] })

  const form = reactive(emptyInvoiceForm())
  const accessories = useInvoiceAccessories(form)
  const isProduction = computed(() => form.order_type === 'production')
  const hair = useInvoiceHairItems(form, accessories.hairItems, isProduction, entryOptions)
  const {
    addLine, appendImportedLines, loadEntryOptions, loadLineOptions, onCustomFieldChange,
    onLineDiscountChange, onLineFilterChange, onPriceInput, refreshLinePrice, removeLine,
    updateLineTotal,
  } = hair

  const formHairPrice = accessories.hairAmount
  const formLineDiscountTotal = accessories.hairDiscount
  const formProductTotal = computed(() => sumLineNet(form.items))
  // 订单总金额（基数）= 产品+包装+运费，不含手续费（重定义 2026-07-24）：
  // 既是手续费自动计算的乘数基数，也是页脚「订单总金额」展示口径
  const formBaseAmount = computed(() => calculateInvoiceTotal(
    formProductTotal.value,
    form.internal_accessory,
    form.shipping_fee,
    0,
  ))
  // 应付合计（含手续费）= 基数 + 手续费：结算/尾款/导出的对外口径（保持不变）
  const formTotal = computed(() => calculateInvoiceTotal(
    formProductTotal.value,
    form.internal_accessory,
    form.shipping_fee,
    form.surcharge_amount,
  ))
  const settlementError = computed(() => {
    if (form.internal_received == null) return ''
    if (Number(form.internal_received) > formTotal.value) return '预付款不能超过总金额'
    return settlementMatchesTotal(formTotal.value, form.internal_received, form.internal_balance)
      ? ''
      : '预付款与尾款之和必须等于总金额'
  })

  // 小满标记的智能默认只在用户没碰过开关时生效；编辑既有单一律尊重存值
  const okkiFlagsTouched = reactive({ newDeal: false, freeShipping: false })

  function markOkkiFlagTouched(key) {
    okkiFlagsTouched[key] = true
  }

  watch(() => form.shipping_fee, fee => {
    if (okkiFlagsTouched.freeShipping) return
    form.okki_free_shipping = Number(fee || 0) > 0 ? 0 : 1
  })

  // 手续费自动计算（2026-07-24）：选付款方式（PayPal 5% / 信保便捷发货 3% / TT 0）
  // 或订单总金额变化时，按 费率×基数 自动填手续费；报关/未选=不自动、用户手填；
  // 用户手改过手续费后不再自动覆盖，直到重新选付款方式。
  // 「上次订单成交日期」参考，仅展示（新成交时为空）。
  const lastOrderDate = ref('')
  let handlingFeeTouched = false

  function markHandlingFeeTouched() {
    handlingFeeTouched = true
  }

  function autofillHandlingFee() {
    const rate = handlingFeeRate(form.internal_payment_method)
    if (rate == null) return // 报关/未选：不自动算，保留用户手填值
    form.surcharge_amount = computeHandlingFee(rate, formBaseAmount.value)
  }

  // 付款方式用 @change 触发（仅用户操作，避开 resetForm 程序化赋值误触发覆盖存值）
  function onPaymentMethodChange() {
    handlingFeeTouched = false
    autofillHandlingFee()
  }

  // 基数变化：已选比例方式且用户未手改时跟随重算。编辑既有单 touched 起始为 true，
  // 不会在加载明细时冲掉存值；新建时付款方式为空、autofill 天然是 no-op
  watch(formBaseAmount, () => {
    if (handlingFeeTouched) return
    autofillHandlingFee()
  })

  watch([formTotal, () => form.internal_received], ([total, prepayment]) => {
    form.internal_balance = calculateBalance(total, prepayment)
  }, { flush: 'sync' })

  const normalizeLine = line => line.product_kind === 'accessory'
    ? normalizeAccessoryRow(line)
    : normalizeHairRow(line)

  // 竞态守卫（cerebrum 2026-05-26 loadMore/doSearch 同款教训）：
  // 快速切换客户或切换 drawer 时，先发后至的过期响应不得覆盖当前表单
  let contactFillSeq = 0
  let customerRuleSeq = 0
  let customerSearchSeq = 0
  let contactSearchSeq = 0
  let invoiceNoSeq = 0
  // 用户手输过发票号后，建议号不再覆盖
  let invoiceNoEdited = false

  function resetForm(data = emptyInvoiceForm()) {
    contactFillSeq++
    customerRuleSeq++
    invoiceNoSeq++
    // 每次开单复位为默认私海（上一单里切过全量不带到下一单）
    privateOnlyCompany.value = true
    privateOnlyContact.value = true
    // 编辑既有单（有 id）：发票号视为已确认，建议号不覆盖
    invoiceNoEdited = Boolean(data.id)
    invoiceNoTaken.value = false
    // 编辑既有单（有 id）时开关视为已人工确认，智能默认不再覆盖
    okkiFlagsTouched.newDeal = Boolean(data.id)
    okkiFlagsTouched.freeShipping = Boolean(data.id)
    // 编辑既有单：手续费视为已确认，加载明细/基数变化不自动覆盖存值
    handlingFeeTouched = Boolean(data.id)
    lastOrderDate.value = ''
    Object.assign(form, emptyInvoiceForm(), {
      ...data,
      shipping_fee: Number(data.shipping_fee || 0),
      surcharge_amount: Number(data.surcharge_amount || 0),
      internal_discount: normalizeDiscount(data.internal_discount),
      packaging_quantity: Number(data.packaging_quantity || 0),
      internal_accessory: Number(data.internal_accessory || 0),
      // 存量 NULL 标记（068 前老单）镜像服务端兜底口径，不要硬填 1 锁死错误值
      okki_new_deal: data.okki_new_deal ?? 1,
      okki_free_shipping: data.okki_free_shipping ?? (Number(data.shipping_fee || 0) > 0 ? 0 : 1),
      okki_first_return: data.okki_first_return ?? 0,
      items: (data.items || []).map(normalizeLine),
    })
    selectedCustomer.value = form.customer_id
      ? { company_id: form.customer_id, company_name: form.customer_name }
      : null
    ensureCustomerOption(selectedCustomer.value) // 编辑回显：客户可能不在当前候选里
    selectedContact.value = null
    contactOptions.value = []
    customerRule.value = null
    if (form.customer_id) {
      loadCustomerRule()
      // 编辑回显路径不走 fillContactDefaults（避免覆盖存的联系人），单独取上次订单日期
      refreshLastOrderDate()
    }
  }

  // el-select 按 value-key 在已渲染 options 里找到匹配项才能显示标签：
  // 联系人反向定位/编辑回显注入的客户若不在候选里，输入框会显示空白。
  // 候选里已有同 company_id 的 → selectedCustomer 复用候选对象引用
  // （顺带消掉 number/string 类型差导致的匹配失败）；没有 → 注入候选头部。
  function ensureCustomerOption(customer) {
    if (!customer) return
    const match = customerOptions.value.find(
      c => String(c.company_id) === String(customer.company_id),
    )
    if (match) {
      if (match !== customer) selectedCustomer.value = match
    } else {
      customerOptions.value.unshift(customer)
    }
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
      // 搜索响应会整体替换候选，把当前选中项补回去，否则选中标签变空白
      ensureCustomerOption(selectedCustomer.value)
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
    accessories.invalidateCustomerContext()
    // 联动：公司变了，已选联系人若不属于新公司即失效；候选收敛到新公司名下
    if (selectedContact.value && String(selectedContact.value.company_id) !== form.customer_id) {
      selectedContact.value = null
    }
    searchContacts('')
    await Promise.all([loadCustomerRule(), fillContactDefaults()])
    // 客户变化 → 客户价规则变化，所有明细价重算
    await Promise.all(accessories.hairItems.value.map(line => refreshLinePrice(line)))
    await accessories.refreshAccessoryPrices()
  }

  async function onCurrencyChange() {
    form.currency = String(form.currency || '').trim().toUpperCase()
    accessories.invalidateCustomerContext()
    await accessories.refreshAccessoryPrices()
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
      ensureCustomerOption(selectedCustomer.value)
      accessories.invalidateCustomerContext()
      await Promise.all([loadCustomerRule(), fillContactDefaults()])
    }
    // 选中联系人是明确意图：整体覆盖联系字段（覆盖快照回填；残留他人联系方式是错单风险）
    form.contact_name = contact.name || ''
    form.contact_phone = contact.tel || ''
    form.contact_email = contact.email || ''
    if (companyChanged) {
      await Promise.all(accessories.hairItems.value.map(line => refreshLinePrice(line)))
      await accessories.refreshAccessoryPrices()
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
    // 首返旁「上次订单成交日期」参考（新成交无历史单 → 空）
    lastOrderDate.value = defaults.last_order_date || ''
  }

  // 编辑回显专用：只取上次订单日期，不触碰联系人/新成交等存值
  let lastOrderSeq = 0
  async function refreshLastOrderDate() {
    const seq = ++lastOrderSeq
    let date = ''
    if (form.customer_id) {
      try {
        const defaults = await getCustomerContactDefaults(form.customer_id) || {}
        date = defaults.last_order_date || ''
      } catch {
        date = '' // 拦截器已统一提示，参考信息静默跳过
      }
    }
    if (seq === lastOrderSeq) lastOrderDate.value = date
  }

  async function openCreate(orderType = 'stock') {
    resetForm()
    form.order_type = orderType
    // 业务员信息默认当前登录用户（可改）；后端 create 对空字段还有一层兜底
    const me = useAuthStore().user
    if (me) {
      form.sales_user_name = me.username || ''
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

  // ── 保存 ────────────────────────────────────────────

  async function saveDraft() {
    if (form.items.some(line => Number(line.total_price || 0) < 0)) {
      ElMessage.warning('产品行折扣不能超过该行金额')
      return null
    }
    if (formTotal.value < 0) {
      ElMessage.warning('折扣金额不能超过订单中可抵扣的金额')
      return null
    }
    if (settlementError.value) {
      ElMessage.warning(settlementError.value)
      return null
    }
    const saved = form.id
      ? await updateInvoice(form.id, buildInvoicePayload(form, formLineDiscountTotal.value))
      : await createInvoice(buildInvoicePayload(form, formLineDiscountTotal.value))
    resetForm(saved)
    ElMessage.success('发票已保存')
    onSaved?.()
    return saved
  }

  // 保存 → 校验 → 推送小满一步到位；校验/推送失败留在抽屉里让用户就地修，成功才收工关闭
  async function saveAndSync() {
    const saved = await saveDraft() // saveDraft 内已触发 onSaved 刷新列表
    if (!saved) return
    const synced = await validateThenSync(form.id, showIssues)
    onSaved?.() // 同步会改单据状态，列表需按最新状态再刷一次
    if (synced) drawerVisible.value = false
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
    canTogglePrivate,
    okkiBound,
    invoiceNoTaken,
    entryOptions,
    form,
    hairItems: accessories.hairItems,
    accessoryItems: accessories.accessoryItems,
    accessoryOptions: accessories.accessoryOptions,
    accessoryLoading: accessories.accessoryLoading,
    formHairPrice,
    formLineDiscountTotal,
    formAccessoryAmount: accessories.accessoryAmount,
    formAccessoryDiscount: accessories.accessoryDiscountTotal,
    formProductTotal,
    formBaseAmount,
    formTotal,
    lastOrderDate,
    settlementError,
    isProduction,
    searchCustomers,
    searchContacts,
    onCustomerChange,
    onCurrencyChange,
    onContactChange,
    onInvoiceNoInput,
    onInvoiceNoBlur,
    openCreate,
    openEdit,
    addLine,
    addAccessory: accessories.addAccessory,
    selectAccessory: accessories.selectAccessory,
    removeAccessory: accessories.removeAccessory,
    searchAccessoryOptions: accessories.searchAccessoryOptions,
    updateAccessoryTotal: accessories.updateAccessoryTotal,
    removeLine,
    loadLineOptions,
    onLineFilterChange,
    onCustomFieldChange,
    onPriceInput,
    onLineDiscountChange,
    updateLineTotal,
    appendImportedLines,
    saveDraft,
    saveAndSync,
    showIssues,
    markOkkiFlagTouched,
    onPaymentMethodChange,
    markHandlingFeeTouched,
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
