import { msgWarning, msgSuccessText, alertAction, confirmAction, isFeedbackCancelled } from '@/utils/feedback'
import { newRequestKey } from '@/utils/requestKey'
import { formatMoney } from '@/utils/money'
import { computed, nextTick, onScopeDispose, reactive, ref, watch } from 'vue'
import { useLinkedInvoiceSync } from './useLinkedInvoiceSync'
import { invoiceBusinessSignature, invoiceOrderSignature } from './invoiceReceiptState'
import { useInvoiceItemGroups } from './useInvoiceItemGroups'

import {
  checkInvoiceNo,
  createInvoice,
  createInvoiceFromScreenshot,
  getCustomerContactDefaults,
  getCustomerRule,
  getInvoice,
  getInvoiceAssignees,
  getInvoiceMerchandisers,
  getPreviousInvoiceNo,
  searchInvoiceCustomerOptions,
  suggestInvoiceNo,
  updateInvoice,
  updateInvoiceItemGroups,
} from '@/api/invoice'
import { INVOICE_SYNC_OUTCOME, validateThenSync } from './invoiceSyncFlow'
import { useAuthStore } from '@/stores/auth'
import { invoiceIsLocal } from '@/views/commerce-transition/routeState'
import {
  applyTotalDiscountToRows,
  calculateBalance,
  calculateInvoiceTotal,
  computeHandlingFee,
  handlingFeeRate,
  normalizeDiscount,
  settlementMatchesTotal,
  sumLineNet,
  toMoneyCents,
} from './invoiceSettlement'
import { normalizeAccessoryRow } from './accessoryPricing'
import { useInvoiceAccessories } from './useInvoiceAccessories'
import {
  buildInvoicePayload,
  emptyInvoiceForm,
  invoiceQuantityIssue,
  isInvoicePlaceholder,
  INVOICE_NO_MAX_LENGTH,
  normalizeHairRow,
  screenshotInvoiceNo,
  screenshotOrderName,
} from './invoiceEditorState'
import { customerOptionKey, useInvoiceCustomerSearch } from './useInvoiceCustomerSearch'
import { useInvoiceHairItems } from './useInvoiceHairItems'

export const CURL_OPTIONS = ['Straight', 'Body Wave', 'Deep Wave', 'Loose Wave', 'Kinky Curly', 'Water Wave']

export function useInvoiceEditor({ onSaved } = {}) {
  const drawerVisible = ref(false)
  // 旧版下单入口（过渡期）：与新版抽屉共享同一份表单状态，同一时间只开一个
  const legacyVisible = ref(false)
  const salesUserOptions = ref([])
  const selectedCustomer = ref(null)
  const customerRule = ref(null)
  // 「仅显示私海客户」（2026-07-14 亮哥定版）：所有人默认私海；
  // invoice_private_filter:read 只控制勾选框显隐=能否切到全量视图。
  // 无权限用户勾选框隐藏、恒定私海——未绑定 OKKI 时唯一出路是去绑定（提示文案区分）
  const canTogglePrivate = computed(() => useAuthStore().hasPermission('invoice_private_filter:read'))
  const privateOnlyCompany = ref(true)
  // false = 当前账号未绑定 OKKI，私海筛选无从判定（前端提示去绑定）
  const okkiBound = ref(true)
  const invoiceNoTaken = ref(false)
  const saveAndSyncSubmitting = ref(false)
  const orderSaving = ref(false)
  const entryOptions = ref({ displays: [], models: [], colors: [], sizes: [], units: [] })
  // 指定跟单员候选（「跟单员」角色在职用户）；同业务员同类型上一单号（订单号旁的红色提醒）
  const merchandiserOptions = ref([])
  const previousInvoiceNo = ref('')

  const form = reactive(emptyInvoiceForm())
  const savedSignature = ref('')
  const savedBusinessSignature = ref('')
  const loadedGroupVersion = ref(null)
  const lastSaveType = ref('business')
  const syncCompletionMessage = ref('')
  let pendingLinkedCompletion = null
  let localAttempt = null
  let entrySequence = 0
  const editorOpen = computed(() => drawerVisible.value || legacyVisible.value)
  const editorBusy = computed(() => orderSaving.value || saveAndSyncSubmitting.value || linked.busy.value || linked.loading.value
    || form.receipt_uploading || form.receipt_action_busy || form.receipt_remark_saving)
  const currentPayload = (payload = buildInvoicePayload(form, formLineDiscountTotal.value), receiptStatus = form.receipt_draft?.status) => {
    const receipt = payload.receipt_draft
    // Generated receipts are persisted separately. The receipt panel also creates
    // an empty zero-value draft on mount; neither is an unsaved order edit.
    if (receipt && ((receiptStatus && receiptStatus !== 'draft')
      || (!Number(receipt.amount) && !Number(receipt.bank_charge) && !receipt.attachment_ids.length && !receipt.remark))) {
      payload.receipt_draft = null
    }
    return payload
  }
  const currentSignature = (payload, receiptStatus) => JSON.stringify(currentPayload(payload, receiptStatus))
  const currentBusinessSignature = (payload, receiptStatus) => invoiceBusinessSignature(currentPayload(payload, receiptStatus))
  const hasOnlyGroupChanges = () => Boolean(
    form.id && savedSignature.value !== currentSignature()
    && savedBusinessSignature.value === currentBusinessSignature(),
  )
  const hasUnsavedChanges = computed(() => !form.id || savedSignature.value !== currentSignature()
    || form.receipt_proof_dirty || form.receipt_remark_editing || form.receipt_action_open)
  let closeConfirmation = null
  async function confirmEditorClose() {
    if (!editorOpen.value) return true
    if (editorBusy.value) {
      msgWarning('订单正在保存、同步或处理回款，请等待完成后再关闭')
      return false
    }
    if (!hasUnsavedChanges.value) return true
    if (closeConfirmation) return closeConfirmation
    closeConfirmation = (async () => {
      try {
        await confirmAction(`订单 ${form.invoice_no || '（未编号）'} 有尚未保存的内容，关闭后将丢失。确定关闭？`, '未保存提醒', {
          type: 'warning', confirmButtonText: '放弃修改并关闭', cancelButtonText: '继续编辑',
          closeOnClickModal: false,
        })
        // The user may have started a save while this confirmation was open.
        return !editorBusy.value
      } catch (error) {
        if (isFeedbackCancelled(error)) return false
        throw error
      } finally { closeConfirmation = null }
    })()
    return closeConfirmation
  }
  async function beforeEditorClose(done) {
    if (await confirmEditorClose()) done()
  }
  async function closeEditor() {
    if (await confirmEditorClose()) {
      drawerVisible.value = false
      legacyVisible.value = false
    }
  }
  function handleBeforeUnload(event) {
    if (!editorOpen.value || (!editorBusy.value && !hasUnsavedChanges.value)) return
    event.preventDefault()
    event.returnValue = ''
  }
  function showSyncCompletion(invoiceNo) {
    syncCompletionMessage.value = `${invoiceNo}订单号已保存并同步完成`
  }
  const contactDetailsExpanded = ref(true)
  const contactDetailsComplete = computed(() => [
    form.contact_name, form.contact_phone, form.contact_email, form.delivery_address,
  ].every(value => String(value ?? '').trim().length > 0))
  // 缺项始终可见；手动补齐时不自动收起，避免输入中途丢失焦点。
  watch(contactDetailsComplete, complete => {
    if (!complete) contactDetailsExpanded.value = true
  }, { flush: 'sync' })
  const quantityErrorRow = ref(null)
  watch(() => quantityErrorRow.value?.quantity, quantity => {
    if (Number.isInteger(quantity) && quantity > 0) quantityErrorRow.value = null
  })
  const linked = useLinkedInvoiceSync(async id => {
    const current = await getInvoice(id)
    if (form.id === id && !hasUnsavedChanges.value) resetForm(current)
    if (form.id === id && pendingLinkedCompletion?.id === id && linked.operation.value?.status === 'done') {
      showSyncCompletion(pendingLinkedCompletion.invoiceNo)
      pendingLinkedCompletion = null
    }
    onSaved?.()
  })
  const loadedUpdatedAt = ref(null)
  const customerSearch = useInvoiceCustomerSearch({
    request: searchInvoiceCustomerOptions,
    scope: () => ({ private_only: privateOnlyCompany.value, sales_user_id: form.sales_user_id }),
    selected: selectedCustomer,
    onBound: value => { okkiBound.value = value },
  })
  const { options: customerOptions, loading: customerLoading, search: searchCustomers } = customerSearch
  const accessories = useInvoiceAccessories(form)
  const isProduction = computed(() => form.order_type === 'production')
  const itemGroups = useInvoiceItemGroups(form)
  const hair = useInvoiceHairItems(form, accessories.hairItems, isProduction, entryOptions, {
    getTargetGroupKey: itemGroups.getTargetGroupKey,
    getSourceItems: itemGroups.getSourceItems,
  })
  const {
    addBlankLine, copyLine, appendImportedLines, loadEntryOptions, loadLineOptions, onCustomFieldChange,
    onLineDiscountChange, onLineFilterChange, onPriceInput, refreshLinePrice, removeLine, removeLines,
    updateLineTotal,
  } = hair

  const formHairPrice = accessories.hairAmount
  const formLineDiscountTotal = accessories.hairDiscount
  const loadedOrderSignature = ref('')
  watch(() => [loadedOrderSignature.value, invoiceOrderSignature(currentPayload())], ([loaded, current]) => {
    form.receipt_order_dirty = Boolean(form.id && loaded && loaded !== current)
  }, { flush: 'sync' })
  // 总折扣录入框（费用与结算卡底部）：默认=产品行折扣合计（正数展示）；手改后均分到产品行
  const formHairDiscountAbs = computed(() => Math.abs(Number(formLineDiscountTotal.value || 0)))
  function applyTotalDiscount(value) {
    const count = applyTotalDiscountToRows(accessories.hairItems.value, value)
    if (!count) {
      msgWarning('没有可分摊折扣的产品行')
    }
    return count
  }
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
    if (form.order_type === 'presale') return ''
    if (form.internal_received == null) return ''
    if (Number(form.internal_received) > formTotal.value) return '预付款不能超过总金额'
    return settlementMatchesTotal(formTotal.value, form.internal_received, form.internal_balance)
      ? ''
      : '预付款与尾款之和必须等于总金额'
  })

  // 小满标记的智能默认只在用户没碰过开关时生效；编辑既有单一律尊重存值
  const okkiFlagsTouched = reactive({ newDeal: false, freeShipping: false, firstReturn: false })

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
    const rate = handlingFeeRate(form.internal_payment_method)
    if (rate == null) {
      // 切到报关/清空：清掉别的付款方式公式留下的自动残值，由用户显式手填
      form.surcharge_amount = 0
      return
    }
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
  let gradeEditSeq = 0
  let customerGradeReady = true
  function markCustomerGradeTouched() {
    gradeEditSeq++
    customerGradeReady = true
  }

  let contactFillSeq = 0
  let remarkEditSeq = 0
  // 同步记录手动修改（包括清空），防止迟到的默认值覆盖当前输入。
  watch(() => form.remark, () => { remarkEditSeq++ }, { flush: 'sync' })
  let customerRuleSeq = 0
  let customerSelectionSeq = 0
  let customerContextSeq = 0
  let customerDefaultsPromise = Promise.resolve()
  watch(() => form.transaction_route, () => { customerContextSeq++; customerSelectionSeq++; contactFillSeq++; customerRuleSeq++; accessories.invalidateCustomerContext() }, { flush: 'sync' })
  let invoiceNoSeq = 0
  let prevNoSeq = 0
  // 用户手输过发票号后，建议号不再覆盖
  let invoiceNoEdited = false

  // Register only while protection is needed; remove on scope disposal as well.
  if (typeof window !== 'undefined') {
    watch(() => editorOpen.value && (editorBusy.value || hasUnsavedChanges.value), protect => {
      window.removeEventListener('beforeunload', handleBeforeUnload)
      if (protect) window.addEventListener('beforeunload', handleBeforeUnload)
    }, { flush: 'sync' })
    onScopeDispose(() => window.removeEventListener('beforeunload', handleBeforeUnload))
  }

  function resetForm(data = emptyInvoiceForm()) {
    quantityErrorRow.value = null
    loadedUpdatedAt.value = data.edit_version || null
    loadedGroupVersion.value = data.item_groups_version || null
    contactFillSeq++
    gradeEditSeq++
    customerGradeReady = true
    customerSelectionSeq++
    customerContextSeq++
    customerSearch.reset()
    customerDefaultsPromise = Promise.resolve()
    customerRuleSeq++
    invoiceNoSeq++
    prevNoSeq++
    previousInvoiceNo.value = ''
    // 每次开单复位为默认私海（上一单里切过全量不带到下一单）
    privateOnlyCompany.value = true
    // 编辑既有单（有 id）：发票号视为已确认，建议号不覆盖
    invoiceNoEdited = Boolean(data.id)
    invoiceNoTaken.value = false
    // 编辑既有单（有 id）时开关视为已人工确认，智能默认不再覆盖
    okkiFlagsTouched.newDeal = Boolean(data.id)
    okkiFlagsTouched.freeShipping = Boolean(data.id)
    okkiFlagsTouched.firstReturn = Boolean(data.id)
    // 编辑既有单：手续费视为已确认，加载明细/基数变化不自动覆盖存值
    handlingFeeTouched = Boolean(data.id)
    lastOrderDate.value = ''
    Object.assign(form, emptyInvoiceForm(), {
      ...data,
      transaction_route: data.transaction_route || data.transaction_mode || 'legacy',
      local_customer_id: data.local_customer_id || (String(data.customer_id || '').startsWith('ark:') ? Number(String(data.customer_id).slice(4)) : null),
      receipt_draft: data.receipt_draft ? { ...data.receipt_draft, amount: data.receipt_draft.amount == null ? 0 : Number(data.receipt_draft.amount) } : null,
      shipping_fee: Number(data.shipping_fee || 0),
      surcharge_amount: Number(data.surcharge_amount || 0),
      internal_discount: normalizeDiscount(data.internal_discount),
      packaging_quantity: Number(data.packaging_quantity || 0),
      internal_accessory: Number(data.internal_accessory || 0),
      // 存量 NULL 标记（068 前老单）保留 null，加载后按 contact-defaults 的服务端
      // 同口径预判回显；不要写死 0，否则编辑保存会锁死错误值
      okki_new_deal: data.okki_new_deal ?? 1,
      okki_free_shipping: data.okki_free_shipping ?? (Number(data.shipping_fee || 0) > 0 ? 0 : 1),
      okki_first_return: data.okki_first_return ?? null,
      items: (data.items || []).map(normalizeLine),
      item_groups_version: data.item_groups_version || null,
    })
    itemGroups.resetItemGroups(data)
    savedSignature.value = currentSignature()
    savedBusinessSignature.value = currentBusinessSignature()
    loadedOrderSignature.value = invoiceOrderSignature(currentPayload())
    contactDetailsExpanded.value = !contactDetailsComplete.value
    selectedCustomer.value = form.customer_id
      ? { company_id: form.customer_id, company_name: form.customer_name }
      : null
    ensureCustomerOption(selectedCustomer.value) // 编辑回显：客户可能不在当前候选里
    customerRule.value = null
    if (form.customer_id && !invoiceIsLocal(form)) {
      loadCustomerRule()
      // 编辑回显路径不走 fillContactDefaults（避免覆盖存的联系人），单独取上次订单日期
      refreshLastOrderDate()
    }
  }

  function ensureCustomerOption(customer) {
    if (customer) customer.option_key = customerOptionKey(customer)
  }

  watch(privateOnlyCompany, () => { searchCustomers('') })

  // 选用刚从 OKKI 同步的客户（InvoiceCustomerSyncEntry 回调）：必须过当前私海
  // 筛选——同步成功≠归属当前业务员（归属他人时同步结果里已展示负责人，这里
  // 明确提示，不静默绕过私海限制）。返回是否选用成功（成功才关弹框）。
  async function selectSyncedCustomer(res) {
    await searchCustomers(String(res.company_id))
    const found = customerSearch.findCustomer(res.company_id)
    if (!found) {
      msgWarning('该客户已同步，但不在当前私海范围内（负责人见同步结果），无法选用')
      return false
    }
    selectedCustomer.value = found
    await onCustomerChange(found)
    return true
  }

  async function loadCustomerRule() {
    const seq = ++customerRuleSeq
    try {
      const rule = form.customer_id ? await getCustomerRule(form.customer_id) : null
      if (seq === customerRuleSeq) customerRule.value = rule
    } catch {
      if (seq === customerRuleSeq) customerRule.value = null
    }
  }

  // 整单粘贴：TO 名称 → 私海候选中唯一公司级匹配才自动选用；多候选/无匹配交还人工
  async function matchWholeOrderCustomer(name) {
    await searchCustomers(String(name || '').trim())
    const companies = customerOptions.value.filter(option => option.kind !== 'contact')
    if (companies.length === 1) return { status: 'matched', option: companies[0] }
    if (companies.length > 1) return { status: 'multiple', count: companies.length }
    return { status: 'none' }
  }

  // 整单粘贴应用：付款方式先于手续费（选付款方式会触发费率重算，手填手续费随后覆盖并标记手改）
  async function applyWholeOrderPaste(parsed) {
    if (parsed.productPreview?.rows?.length && !itemGroups.getTargetGroupKey()) {
      msgWarning('请先选择或新建一个明细分组，再粘贴产品明细')
      return
    }
    const applied = []
    const skipped = []
    if (parsed._customerOption) {
      selectedCustomer.value = parsed._customerOption
      await onCustomerChange(parsed._customerOption)
      applied.push('客户')
    } else if (parsed.customer_name) {
      skipped.push(`客户「${parsed.customer_name}」需手动选择`)
    }
    if (parsed.contact_phone) { form.contact_phone = parsed.contact_phone; applied.push('电话') }
    if (parsed.contact_email) { form.contact_email = parsed.contact_email; applied.push('邮箱') }
    if (parsed.delivery_address) { form.delivery_address = parsed.delivery_address; applied.push('收货地址') }
    if (parsed.payment_method) {
      form.internal_payment_method = parsed.payment_method
      onPaymentMethodChange()
      applied.push('付款方式')
    } else if (parsed.payment_raw) {
      skipped.push(`付款方式「${parsed.payment_raw}」未匹配，请手选`)
    }
    if (parsed.express_channel) { form.express_channel = parsed.express_channel; applied.push('快递渠道') }
    if (parsed.handling_fee != null) {
      form.surcharge_amount = parsed.handling_fee
      markHandlingFeeTouched()
      applied.push('手续费')
    }
    if (parsed.packaging_fee != null) { form.internal_accessory = parsed.packaging_fee; applied.push('包装费用') }
    if (parsed.shipping_fee != null) { form.shipping_fee = parsed.shipping_fee; applied.push('运费') }
    // 产品明细先于折扣：整单粘贴的折扣总价需要产品行就位后才能均分
    if (parsed.productPreview?.rows?.length) {
      if (appendImportedLines(parsed.productPreview.rows, parsed.productPreview.fingerprint)) {
        applied.push(`产品明细 ${parsed.productPreview.rows.length} 行`)
      } else {
        skipped.push('产品明细与当前发票已有批次重复，未重复加入')
      }
    }
    if (parsed.discount_total != null) {
      if (applyTotalDiscountToRows(accessories.hairItems.value, parsed.discount_total)) {
        applied.push('折扣总价（已均分到产品行）')
      } else {
        skipped.push('折扣总价：暂无产品行可分摊，请录入产品后在折扣框填写')
      }
    }
    if (applied.length) msgSuccessText(`整单粘贴已填入：${applied.join('、')}`)
    if (skipped.length) msgWarning(skipped.join('；'))
  }

  async function onCustomerChange(customer) {
    const seq = ++customerSelectionSeq
    contactDetailsExpanded.value = true
    const sameCompanyContact = customer?.kind === 'contact' && String(customer.company_id) === form.customer_id
    const contextSeq = sameCompanyContact ? customerContextSeq : ++customerContextSeq
    selectedCustomer.value = customer || null
    ensureCustomerOption(customer)
    form.customer_id = customer?.company_id == null ? '' : String(customer.company_id)
    form.customer_name = customer?.company_name || ''
    if (!sameCompanyContact) {
      accessories.invalidateCustomerContext()
      customerDefaultsPromise = fillContactDefaults()
      await Promise.all([loadCustomerRule(), customerDefaultsPromise])
    } else {
      // Changing only the contact preserves this order's address and prices.
      await customerDefaultsPromise
    }
    if (contextSeq !== customerContextSeq) return
    if (seq === customerSelectionSeq && customer?.kind === 'contact') {
      // Explicit contact choice wins over the latest invoice's contact snapshot.
      form.contact_name = customer.name || ''
      form.contact_phone = customer.tel || ''
      form.contact_email = customer.email || ''
    }
    if (seq === customerSelectionSeq) contactDetailsExpanded.value = !contactDetailsComplete.value
    if (!sameCompanyContact) {
      await Promise.all(accessories.hairItems.value.map(line => refreshLinePrice(line)))
      if (contextSeq === customerContextSeq) await accessories.refreshAccessoryPrices()
    }
  }

  async function onCurrencyChange() {
    if (invoiceIsLocal(form)) { form.currency = String(form.currency || '').trim().toUpperCase(); return }
    form.currency = String(form.currency || '').trim().toUpperCase()
    accessories.invalidateCustomerContext()
    await accessories.refreshAccessoryPrices()
  }

  // 联系人/地址是客户属性：选客户后用该客户最近一张发票的快照整体覆盖（含清空），
  // 残留上一个客户的地址是错单风险
  async function fillContactDefaults() {
    const seq = ++contactFillSeq
    // 只为新建单回填备注；切客户时立即清除上一客户的内容。
    if (!form.id) form.remark = ''
    const remarkSeq = remarkEditSeq
    form.customer_grade = null
    customerGradeReady = false
    const gradeSeq = gradeEditSeq
    let defaultsLoaded = false
    let defaults = {}
    if (form.customer_id) {
      try {
        // 截图导入的订单已存在于 OKKI：排除本单，避免把自己算成历史单
        const excludeOrderId = form.source_type === 'okki_screenshot' ? form.source_order_id : undefined
        defaults = await getCustomerContactDefaults(form.customer_id, excludeOrderId) || {}
        defaultsLoaded = true
      } catch {
        defaults = {} // 拦截器已统一提示，回填静默跳过
        // 预判失败：新建单保留 null 交服务端同口径兜底，避免静默落成「首返=否」
        if (!form.id && !okkiFlagsTouched.firstReturn) form.okki_first_return = null
      }
    }
    if (seq !== contactFillSeq) return // 期间又切了客户/换了单据，丢弃过期响应
    if (!form.id && remarkSeq === remarkEditSeq) form.remark = defaults.remark || ''
    if (gradeSeq === gradeEditSeq && defaultsLoaded) {
      form.customer_grade = defaults.customer_grade || null
      customerGradeReady = true
    }
    form.contact_name = defaults.contact_name || ''
    form.contact_phone = defaults.contact_phone || ''
    form.contact_email = defaults.contact_email || ''
    form.delivery_address = defaults.delivery_address || ''
    // 「是否新成交」预判：该客户在小满无历史订单 → 新成交（用户碰过开关则不动）
    if (!okkiFlagsTouched.newDeal && typeof defaults.has_xiaoman_orders === 'boolean') {
      form.okki_new_deal = defaults.has_xiaoman_orders ? 0 : 1
    }
    // 「是否首返」预判：该客户恰好一张 OKKI 历史订单 → 本单是其第一次返单
    if (!okkiFlagsTouched.firstReturn && typeof defaults.first_return_default === 'number') {
      form.okki_first_return = defaults.first_return_default ? 1 : 0
    }
    // 首返旁「上次订单成交日期」参考（新成交无历史单 → 空）
    lastOrderDate.value = defaults.last_order_date || ''
  }

  // 编辑回显专用：取上次订单日期，并在存量首返为 NULL 时回显服务端同口径预判
  let lastOrderSeq = 0
  async function refreshLastOrderDate() {
    const seq = ++lastOrderSeq
    let date = ''
    if (form.customer_id) {
      try {
        // 已推单排除本单；截图导入排除来源订单，避免把本单显示成「上次订单」
        const excludeOrderId = form.xiaoman_order_id
          || (form.source_type === 'okki_screenshot' ? form.source_order_id : undefined)
        const defaults = await getCustomerContactDefaults(form.customer_id, excludeOrderId) || {}
        date = defaults.last_order_date || ''
        // 仅在表单仍为 NULL 时回填，用户已手动选择的值不覆盖
        if (form.okki_first_return == null && typeof defaults.first_return_default === 'number') {
          form.okki_first_return = defaults.first_return_default ? 1 : 0
        }
      } catch {
        date = '' // 拦截器已统一提示，参考信息静默跳过
      }
    }
    if (seq === lastOrderSeq) lastOrderDate.value = date
  }

  async function prepareCreate(orderType = 'stock') {
    resetForm()
    form.order_type = orderType
    await loadSalesUsers()
    const me = useAuthStore().user
    form.sales_user_id = me?.id || salesUserOptions.value[0]?.id || null
    applySalesUserSnapshot()
    addBlankLine()
    linked.load(null)
    searchCustomers('')
    fetchSuggestedInvoiceNo()
    loadMerchandisers()
    refreshPreviousInvoiceNo()
    if (orderType === 'production') loadEntryOptions()
  }

  async function openCreate(orderType = 'stock') {
    const ticket = ++entrySequence
    await prepareCreate(orderType)
    if (ticket !== entrySequence) return
    drawerVisible.value = true
  }

  // 旧版下单入口：同样的初始化流程，只是打开旧版布局抽屉
  async function openLegacyCreate(orderType = 'stock') {
    const ticket = ++entrySequence
    await prepareCreate(orderType)
    if (ticket !== entrySequence) return
    legacyVisible.value = true
  }

  async function openEdit(id) {
    const ticket = ++entrySequence
    const data = await getInvoice(id)
    if (ticket !== entrySequence) return
    resetForm(data)
    if (!invoiceIsLocal(data)) await linked.load(id)
    if (ticket !== entrySequence) return
    await loadSalesUsers()
    if (ticket !== entrySequence) return
    drawerVisible.value = true
    searchCustomers('')
    loadMerchandisers()
    refreshPreviousInvoiceNo()
    if (form.order_type === 'production' && !invoiceIsLocal(form)) loadEntryOptions()
  }

  function cancelEntry() { entrySequence++; customerContextSeq++; customerSelectionSeq++; contactFillSeq++; customerRuleSeq++; customerSearch.reset() }

  async function applyScreenshotPreview(preview) {
    const patch = preview?.invoice_patch
    if (!preview?.ready || !patch) {
      msgWarning('识别结果仍有待处理项，暂不能创建发票')
      return
    }
    const recognizedOrderName = screenshotOrderName(preview)
    const invoiceNo = screenshotInvoiceNo(preview)
    resetForm({ ...patch, invoice_no: invoiceNo, id: null })
    // 截图订单名就是本次发票号；标记为已确认，避免异步建议号覆盖识别结果。
    invoiceNoEdited = Boolean(invoiceNo)
    await loadSalesUsers()
    applySalesUserSnapshot()
    selectedCustomer.value = {
      company_id: patch.customer_id,
      company_name: patch.customer_name,
    }
    ensureCustomerOption(selectedCustomer.value)
    await Promise.all([loadCustomerRule(), fillContactDefaults()])
    drawerVisible.value = true
    loadMerchandisers()
    refreshPreviousInvoiceNo()
    if (!invoiceNo) fetchSuggestedInvoiceNo()
    if (patch.order_type === 'production') loadEntryOptions()
    let successMessage = '订单名称已填入发票号，请确认缺失的结算和联系信息后保存'
    if (!invoiceNo) successMessage = '未识别到订单名称，正在生成系统发票号，请确认后保存'
    else if (recognizedOrderName.length > INVOICE_NO_MAX_LENGTH) {
      successMessage = `订单名称超过 ${INVOICE_NO_MAX_LENGTH} 个字符，已截取后填入发票号，请确认后保存`
    }
    msgSuccessText(successMessage)
  }

  async function loadSalesUsers() {
    const res = await getInvoiceAssignees()
    salesUserOptions.value = res.items || []
  }

  async function loadMerchandisers() {
    try {
      const res = await getInvoiceMerchandisers()
      merchandiserOptions.value = res.items || []
    } catch {
      merchandiserOptions.value = [] // 拦截器已统一提示；候选加载失败不阻塞下单
    }
  }

  // 订单号旁的「上一单」红色提醒：同业务员同类型最近一张订单；提醒性信息，失败静默
  async function refreshPreviousInvoiceNo() {
    previousInvoiceNo.value = ''
    if (!form.sales_user_id) return
    const seq = ++prevNoSeq
    try {
      const res = await getPreviousInvoiceNo({
        sales_user_id: form.sales_user_id,
        order_type: form.order_type,
        exclude_id: form.id || undefined,
      })
      if (seq === prevNoSeq) previousInvoiceNo.value = res.previous_invoice_no || ''
    } catch { /* 提醒性信息静默失败 */ }
  }

  function applySalesUserSnapshot() {
    const selected = salesUserOptions.value.find(user => user.id === form.sales_user_id)
    if (!selected) return
    form.sales_user_name = selected.username || ''
    form.sales_phone = selected.phone || ''
    form.sales_email = selected.email || ''
  }

  async function onSalesUserChange() {
    applySalesUserSnapshot()
    selectedCustomer.value = null
    customerSelectionSeq++
    customerContextSeq++
    contactFillSeq++
    customerRuleSeq++
    form.customer_id = ''
    form.local_customer_id = null
    form.customer_name = ''
    form.customer_grade = null
    form.contact_name = ''
    form.contact_phone = ''
    form.contact_email = ''
    form.delivery_address = ''
    if (!form.id) form.remark = ''
    customerRule.value = null
    accessories.invalidateCustomerContext()
    refreshPreviousInvoiceNo()
    if (invoiceIsLocal(form)) return
    await Promise.all([
      searchCustomers(''),
      ...accessories.hairItems.value.map(line => refreshLinePrice(line)),
      accessories.refreshAccessoryPrices(),
    ])
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
      if (!res.available) msgWarning(`发票号 ${no} 已存在，请更换`)
    } catch {
      // 拦截器已统一提示；保存时后端还有唯一校验兜底
    }
  }

  // ── 保存 ────────────────────────────────────────────

  async function saveDraft(options = {}) {
    if (orderSaving.value) return null
    orderSaving.value = true
    try { return await saveDraftContent(options) }
    finally { orderSaving.value = false }
  }

  async function saveDraftContent(options) {
    const contextSeq = customerContextSeq
    await customerDefaultsPromise
    if (contextSeq !== customerContextSeq) return null
    if (form.receipt_uploading) { msgWarning("请等待回款截图上传完成"); return null }
    if (form.receipt_proof_dirty) { msgWarning("请先保存回款截图变更"); return null }
    if (form.receipt_remark_editing || form.receipt_remark_saving) { msgWarning('请先保存或取消回款备注编辑'); return null }
    if (form.receipt_action_open || form.receipt_action_busy) { msgWarning('请先完成或关闭当前回款操作'); return null }

    const groupOnly = hasOnlyGroupChanges()
    lastSaveType.value = groupOnly ? 'groups' : 'business'
    if (groupOnly) {
      const payload = buildInvoicePayload(form, formLineDiscountTotal.value)
      const submittedSignature = currentSignature()
      const submittedReceiptStatus = form.receipt_draft?.status
      const saved = await updateInvoiceItemGroups(form.id, {
        item_groups: payload.item_groups,
        items: payload.items.filter(line => line.product_kind !== 'accessory').map(line => ({
          id: line.id, group_key: line.group_key,
        })),
        expected_version: loadedUpdatedAt.value,
        expected_authority_epoch: form.authority_epoch ?? null,
        expected_groups_version: loadedGroupVersion.value,
      })
      if (!saved) return null
      return finishInvoiceSave(saved, { created: false, groupOnly, payload, submittedSignature, submittedReceiptStatus })
    }

    if (form.presale_edit_blocked_reason) { msgWarning(form.presale_edit_blocked_reason); return null }
    if (form.items.some(line => Number(line.total_price || 0) < 0)) {
      msgWarning('产品行折扣不能超过该行金额')
      return null
    }
    if (formTotal.value < 0) {
      msgWarning('折扣金额不能超过订单中可抵扣的金额')
      return null
    }
    if (settlementError.value) {
      msgWarning(settlementError.value)
      return null
    }
    const receipt = form.receipt_draft
    if (form.order_type === 'stock' && (!receipt?.status || receipt.status === 'draft') &&
        toMoneyCents(receipt?.amount) > toMoneyCents(formTotal.value)) {
      msgWarning(`本次回款金额 ${formatMoney(receipt.amount)} 不能超过订单总额 ${formatMoney(formTotal.value)} ${form.currency}，请核对后保存`)
      return null
    }
    // 客户等级必填（2026-09 下单页改版）：等级决定价格规则，缺等级不允许保存
    if (!form.customer_grade) {
      msgWarning('请选择客户等级')
      return null
    }
    // 联系信息与快递渠道必填（2026-09-23 下单页改版）
    const missingRequired = []
    if (!String(form.contact_name || '').trim()) missingRequired.push('联系人')
    if (!String(form.contact_phone || '').trim()) missingRequired.push('电话')
    if (!String(form.contact_email || '').trim()) missingRequired.push('邮箱')
    if (!String(form.delivery_address || '').trim()) missingRequired.push('收货地址')
    if (!form.express_channel) missingRequired.push('快递渠道')
    if (missingRequired.length) {
      msgWarning(`请完善必填项：${missingRequired.join('、')}`)
      return null
    }
    const quantityIssue = invoiceQuantityIssue(form.items, form.item_groups)
    if (quantityIssue) {
      quantityErrorRow.value = null
      await nextTick()
      quantityErrorRow.value = quantityIssue.row
      msgWarning(quantityIssue.message)
      return null
    }
    const submittedSignature = currentSignature()
    const submittedReceiptStatus = form.receipt_draft?.status
    const payload = buildInvoicePayload(form, formLineDiscountTotal.value)
    const submittedRows = form.items.filter(line => !isInvoicePlaceholder(line))
    if (invoiceIsLocal(form)) {
      if (!form.local_customer_id || submittedRows.some(line => !line.local_sku_id)) { msgWarning('请选择已核验的本地客户及每行本地 SKU'); return null }
      if (Number(form.receipt_draft?.amount || 0)) { msgWarning('请先清空旧回款草稿，本地订单通过资金与应收登记'); return null }
      payload.receipt_draft = null
      const signature = JSON.stringify(payload)
      if (!localAttempt || localAttempt.signature !== signature) localAttempt = { signature, request_key: newRequestKey() }
      payload.request_key = localAttempt.request_key
    }
    // A failed defaults request must not erase an existing customer grade.
    if (!customerGradeReady) delete payload.customer_grade
    const created = !form.id
    const saved = options.linked
      ? await linked.save(form.id, payload, loadedUpdatedAt.value)
      : form.id
      ? await updateInvoice(form.id, payload)
      : form.source_type === 'okki_screenshot'
        ? await createInvoiceFromScreenshot(payload)
        : await createInvoice(payload)
    if (!saved) return null
    localAttempt = null
    return finishInvoiceSave(saved, { created, groupOnly, payload, submittedRows, submittedSignature, submittedReceiptStatus })
  }

  function finishInvoiceSave(saved, { created, groupOnly, payload, submittedRows, submittedSignature, submittedReceiptStatus }) {
    if (currentSignature() === submittedSignature) resetForm(saved)
    else {
      // Preserve edits made while the request was in flight and keep them dirty.
      const savedItems = Array.isArray(saved.items) ? saved.items : []
      const savedPayload = { ...payload, expected_groups_version: saved.item_groups_version || null }
      if (!groupOnly && savedItems.length === submittedRows.length) {
        savedItems.forEach((savedItem, index) => {
          const source = submittedRows[index]
          const current = form.items.find(row => row === source)
          if (current && savedItem.product_kind === source.product_kind) {
            current.id = savedItem.id
            current.created_at = savedItem.created_at || current.created_at
          }
        })
        savedPayload.items = payload.items.map((item, index) => (
          savedItems[index]?.product_kind === item.product_kind
            ? { ...item, id: savedItems[index].id }
            : item
        ))
      }
      form.id = saved.id
      form.item_groups_version = saved.item_groups_version || null
      loadedUpdatedAt.value = saved.edit_version || null
      loadedGroupVersion.value = saved.item_groups_version || null
      savedSignature.value = currentSignature(savedPayload, submittedReceiptStatus)
      savedBusinessSignature.value = currentBusinessSignature(savedPayload, submittedReceiptStatus)
      loadedOrderSignature.value = invoiceOrderSignature(savedPayload)
    }
    msgSuccessText(groupOnly ? '明细分组已保存' : '发票已保存')
    onSaved?.({ created, invoice: saved })
    return saved
  }

  // 保存 → 校验 → 推送小满；只在确认成功后显示持续提示，失败保留编辑现场。
  async function saveAndSync() {
    if (invoiceIsLocal(form)) { msgWarning('方舟独立订单请保存后在订单履约中确认，不发送小满'); return }
    if (saveAndSyncSubmitting.value) {
      msgWarning('发票正在保存并同步，请勿重复提交')
      return
    }

    saveAndSyncSubmitting.value = true
    try {
      await customerDefaultsPromise
      const groupOnly = hasOnlyGroupChanges()
      if (!groupOnly && ['stock', 'presale'].includes(form.order_type) && Number(form.receipt_draft?.amount || 0) === 0) {
        try {
          await confirmAction('当前回款金额为0，是否确认提交？', '提交确认', {
            type: 'warning', confirmButtonText: '确认提交', cancelButtonText: '取消',
          })
        } catch (error) {
          if (isFeedbackCancelled(error)) return
          throw error
        }
      }
      const useLinked = !groupOnly && Boolean(form.id && form.xiaoman_order_id)
      const saved = await saveDraft({ linked: useLinked })
      if (!saved) return
      if (lastSaveType.value === 'groups') {
        msgSuccessText('订单业务数据未变化，无需同步')
        return
      }
      if (useLinked) {
        pendingLinkedCompletion = { id: saved.id, invoiceNo: saved.invoice_no }
        const result = await linked.run()
        if (result?.status === 'done') {
          showSyncCompletion(saved.invoice_no)
          pendingLinkedCompletion = null
        }
        return
      }
      const outcome = await validateThenSync(form.id, showIssues)
      if (outcome === INVOICE_SYNC_OUTCOME.DUPLICATE) return
      onSaved?.() // 同步会改单据状态，列表需按最新状态再刷一次
      if (outcome === INVOICE_SYNC_OUTCOME.SUCCESS) {
        showSyncCompletion(saved.invoice_no)
        if (!hasUnsavedChanges.value) {
          drawerVisible.value = false
          legacyVisible.value = false
        }
      }
    } finally {
      saveAndSyncSubmitting.value = false
    }
  }

  function showIssues(issues = []) {
    const escapeHtml = value => String(value ?? '')
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;')
    const html = issues
      .map(i => `<p>${escapeHtml(i.field)}: ${escapeHtml(i.message)}</p>`)
      .join('') || '校验未通过'
    alertAction(html, '同步前校验', { dangerouslyUseHTMLString: true, confirmButtonText: '知道了' })
  }

  return {
    ...itemGroups,
    hasOnlyGroupChanges,
    hasUnsavedChanges, editorBusy, confirmEditorClose, beforeEditorClose, closeEditor,
    syncCompletionMessage, handleBeforeUnload,
    quantityErrorRow,
    drawerVisible,
    legacyVisible,
    customerLoading,
    customerOptions,
    salesUserOptions,
    selectedCustomer,
    customerRule,
    customerTotal: customerSearch.total,
    customerHasMore: customerSearch.hasMore,
    loadMoreCustomers: customerSearch.loadMore,
    privateOnlyCompany,
    canTogglePrivate,
    okkiBound,
    invoiceNoTaken,
    saveAndSyncSubmitting,
    receiptLocked: computed(() => orderSaving.value || saveAndSyncSubmitting.value || linked.busy.value || linked.loading.value),
    linkedOperation: linked.operation,
    linkedBusy: linked.busy,
    linkedLoading: linked.loading,
    refreshLinked: () => linked.load(form.id),
    retryLinked: () => linked.run(false),
    recheckLinked: () => linked.run(true),
    closeLinked: linked.close, resolveLinked: linked.resolve,
    entryOptions,
    form,
    contactDetailsExpanded,
    contactDetailsComplete,
    hairItems: accessories.hairItems,
    accessoryItems: accessories.accessoryItems,
    accessoryOptions: accessories.accessoryOptions,
    accessoryLoading: accessories.accessoryLoading,
    formHairPrice,
    formLineDiscountTotal,
    formHairDiscountAbs,
    applyTotalDiscount,
    merchandiserOptions,
    previousInvoiceNo,
    formAccessoryAmount: accessories.accessoryAmount,
    formAccessoryDiscount: accessories.accessoryDiscountTotal,
    formProductTotal,
    formBaseAmount,
    formTotal,
    lastOrderDate,
    settlementError,
    isProduction,
    searchCustomers,
    selectSyncedCustomer,
    matchWholeOrderCustomer,
    applyWholeOrderPaste,
    onCustomerChange,
    onSalesUserChange,
    onCurrencyChange,
    onInvoiceNoInput,
    onInvoiceNoBlur,
    cancelEntry, openCreate,
    openLegacyCreate,
    openEdit,
    applyScreenshotPreview,
    addBlankLine,
    copyLine,
    addAccessory: accessories.addAccessory,
    selectAccessory: accessories.selectAccessory,
    removeAccessory: accessories.removeAccessory,
    removeAccessories: accessories.removeAccessories,
    searchAccessoryOptions: accessories.searchAccessoryOptions,
    updateAccessoryTotal: accessories.updateAccessoryTotal,
    removeLine,
    removeLines,
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
    markCustomerGradeTouched,
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

export function describeCustomerRule(rule) {
  if (!rule) return ''
  const sign = Number(rule.adjust_value) >= 0 ? '+' : ''
  return rule.adjust_type === 'percent'
    ? `标准价 ${sign}${Number(rule.adjust_value)}%`
    : `标准价 ${sign}${Number(rule.adjust_value)}`
}
