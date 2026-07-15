import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import {
  analyzeAfterSalesCase,
  closeAfterSalesCase,
  createAfterSalesCase,
  deleteAfterSalesEvidence,
  downloadAfterSalesEvidence,
  executeAfterSalesCase,
  getAfterSalesCase,
  getAfterSalesOptions,
  getAfterSalesTimeline,
  requestAfterSalesEvidenceWaiver,
  reopenAfterSalesCase,
  retryAfterSalesNotification,
  reviewAfterSalesCase,
  reviewAfterSalesEvidenceWaiver,
  saveAfterSalesDecision,
  searchAfterSalesCustomers,
  searchAfterSalesOrders,
  searchAfterSalesProducts,
  searchAfterSalesReviewers,
  submitAfterSalesCase,
  updateAfterSalesCase,
  uploadAfterSalesEvidence,
  transferAfterSalesApproval,
  withdrawAfterSalesCase,
} from '@/api/aftersales'
import { buildEnglishReply, canEditCase, validateActionDetails, validateEnglishReply } from '../aftersalesRules'

const VALUE_CODES = new Set(['free_rework', 'replacement', 'resend', 'cash_refund', 'discount', 'order_credit', 'freight_subsidy'])
const AMOUNT_CODES = new Set(['cash_refund', 'discount', 'order_credit', 'freight_subsidy'])

function today() {
  const now = new Date()
  const pad = value => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}
function blankForm() {
  return {
    customer_id: '', customer_name_snapshot: '', customer_grade: 'A', order_id: '', order_no_snapshot: '',
    purchase_date: '', feedback_date: today(), feedback_channel: '', product_id: null,
    product_name_snapshot: '', is_custom_product: false, batch_no: '', color_value: '', length_value: '',
    weight_value: 100, weight_unit: 'g', quantity: 1, primary_issue_type: '', secondary_issue_types: [],
    problem_description: '', occurred_stage: '使用几天', care_storage_note: '', affects_end_customer: 'unknown',
    affected_goods_value: 0, affected_goods_currency: 'USD', sales_evidence_confirmed: null, sales_evidence_note: '',
  }
}

function uniqueActions(items = []) {
  return [...new Map(items.map(item => [item.code, { ...item }])).values()]
}

export function useAfterSalesWorkspace() {
  const route = useRoute()
  const router = useRouter()
  const auth = useAuthStore()
  const loading = ref(false)
  const saving = ref(false)
  const analyzing = ref(false)
  const hydrating = ref(false)
  const dirty = ref(false)
  const registrationDirty = ref(false)
  const options = ref({ issue_types: [], actions: [] })
  const caseData = reactive({ current_status: 'draft', evidence_score: 0, evidence_missing_items_json: [], version: 1 })
  const form = reactive(blankForm())
  const timeline = ref({ events: [], reviews: [], ai_runs: [], notifications: [] })
  const evidenceFiles = ref([])
  const customers = ref([])
  const orders = ref([])
  const products = ref([])
  const reviewers = ref([])
  const actions = ref([])
  const replyDraft = ref('')
  const responsibilityClass = ref('')
  const responsibilityReason = ref('')
  const overrideReason = ref('')
  let pollTimer = null
  let allowRouteLeave = false

  const isNew = computed(() => route.params.caseId == null)
  const locked = computed(() => !canEditCase(caseData.current_status))
  const latestAi = computed(() => [...(timeline.value.ai_runs || [])].reverse().find(item => item.status === 'success')?.output || null)
  const currentUserId = computed(() => Number(auth.user?.id))
  const canAdmin = computed(() => auth.hasPermission('aftersales:admin'))
  const canReviewWaiver = computed(() => (
    caseData.current_status === 'awaiting_evidence_waiver'
    && currentUserId.value === Number(caseData.supervisor_user_id_snapshot)
    && auth.hasPermission('aftersales:review')
  ))
  const isProxyReview = computed(() => (
    auth.roles.includes('super_admin')
    && ['awaiting_supervisor', 'awaiting_director'].includes(caseData.current_status)
    && currentUserId.value !== Number(caseData.current_owner_user_id)
  ))
  const canReview = computed(() => (
    (
      (caseData.current_status === 'awaiting_supervisor' && currentUserId.value === Number(caseData.supervisor_user_id_snapshot))
      || (caseData.current_status === 'awaiting_director' && currentUserId.value === Number(caseData.director_user_id_snapshot))
    ) && auth.hasPermission('aftersales:review')
    || isProxyReview.value
  ))

  function hydrate(data) {
    hydrating.value = true
    evidenceFiles.value.forEach(item => { if (item.url?.startsWith('blob:')) URL.revokeObjectURL(item.url) })
    Object.assign(caseData, data)
    Object.assign(form, blankForm(), {
      ...data,
      secondary_issue_types: data.secondary_issue_types_json || [],
    })
    actions.value = uniqueActions(data.selected_actions_json || [])
    replyDraft.value = data.customer_reply_draft || ''
    responsibilityClass.value = data.responsibility_class || ''
    responsibilityReason.value = data.responsibility_reason || ''
    overrideReason.value = data.responsibility_override_reason || ''
    evidenceFiles.value = (data.evidence || []).map(item => ({ ...item, name: item.original_filename, path: item.original_filename, url: '' }))
    if (data.customer_id) customers.value = [{ customer_id: data.customer_id, customer_name: data.customer_name_snapshot }]
    if (data.order_id) orders.value = [{ order_id: data.order_id, order_no: data.order_no_snapshot, amount_usd: data.affected_goods_value }]
    if (data.product_id) products.value = [{ product_id: data.product_id, product_name: data.product_name_snapshot }]
    hydrating.value = false
    dirty.value = false
    registrationDirty.value = false
  }

  async function hydrateEvidencePreviews() {
    await Promise.all(evidenceFiles.value.map(async item => {
      if (!item.mime_type?.startsWith('image/')) return
      try {
        const response = await downloadAfterSalesEvidence(item.id)
        item.url = URL.createObjectURL(response.data)
      } catch {
        item.url = ''
      }
    }))
  }

  async function loadCase() {
    if (isNew.value) return
    const [detail, history] = await Promise.all([getAfterSalesCase(route.params.caseId), getAfterSalesTimeline(route.params.caseId)])
    hydrate(detail.data)
    await hydrateEvidencePreviews()
    timeline.value = history.data || { events: [], reviews: [], ai_runs: [], notifications: [] }
    const ai = latestAi.value
    if (ai && !actions.value.length && canEditCase(caseData.current_status)) {
      hydrating.value = true
      actions.value = uniqueActions(ai.recommended_actions || [])
      replyDraft.value = replyDraft.value || ai.customer_reply_draft?.content || ''
      responsibilityClass.value = responsibilityClass.value || ai.responsibility?.class || ''
      responsibilityReason.value = responsibilityReason.value || (ai.responsibility?.reasoning || []).join('；')
      hydrating.value = false
      dirty.value = false
    }
  }

  async function initialize() {
    loading.value = true
    try {
      const result = await getAfterSalesOptions()
      options.value = result.data || { issue_types: [], actions: [] }
      await loadCase()
    } finally { loading.value = false }
  }

  function registrationPayload() {
    return {
      ...Object.fromEntries(Object.keys(blankForm()).map(key => [key, form[key]])),
      product_id: form.is_custom_product ? null : form.product_id,
      batch_no: form.batch_no || null,
      feedback_channel: form.feedback_channel || null,
      sales_evidence_note: form.sales_evidence_note || null,
    }
  }

  function validateRegistration() {
    const required = [
      ['客户', form.customer_id], ['订单', form.order_id], ['产品', form.product_name_snapshot], ['颜色', form.color_value],
      ['长度', form.length_value], ['问题类型', form.primary_issue_type], ['购买日期', form.purchase_date], ['反馈日期', form.feedback_date],
    ]
    const missing = required.find(([, value]) => !value)
    if (missing) return `请填写${missing[0]}`
    if ((form.problem_description || '').trim().length < 20) return '问题描述至少填写 20 字'
    if ((form.care_storage_note || '').trim().length < 20) return '安装 / 护理 / 存储说明至少填写 20 字'
    if (Number(form.quantity) <= 0 || Number(form.weight_value) <= 0 || Number(form.affected_goods_value) <= 0) return '数量、克重和问题货值必须大于 0'
    if (form.feedback_date < form.purchase_date) return '反馈日期不得早于购买日期'
    return ''
  }

  async function saveDraft({ silent = false } = {}) {
    const error = validateRegistration()
    if (error) { msgError(error); throw new Error(error) }
    saving.value = true
    try {
      const response = isNew.value
        ? await createAfterSalesCase(registrationPayload())
        : await updateAfterSalesCase(caseData.id, registrationPayload())
      hydrate({ ...caseData, ...response.data, evidence: caseData.evidence || evidenceFiles.value })
      if (!isNew.value) await hydrateEvidencePreviews()
      if (isNew.value) {
        allowRouteLeave = true
        await router.replace(`/aftersales/cases/${response.data.id}`)
        allowRouteLeave = false
        await loadCase()
      }
      if (!silent) msgSuccess('保存草稿')
      registrationDirty.value = false
      return response.data
    } finally { saving.value = false }
  }

  async function searchCustomers(keyword) {
    if (!keyword?.trim()) return
    const response = await searchAfterSalesCustomers({ keyword })
    customers.value = response.data?.items || []
  }
  async function customerChanged(id) {
    const item = customers.value.find(candidate => candidate.customer_id === id)
    form.customer_name_snapshot = item?.customer_name || ''
    form.order_id = ''; form.order_no_snapshot = ''; orders.value = []
    if (id) await searchOrders('')
  }
  async function searchOrders(keyword) {
    if (!form.customer_id) return
    const response = await searchAfterSalesOrders({ customer_id: form.customer_id, keyword })
    orders.value = response.data?.items || []
  }
  function orderChanged(id) {
    const item = orders.value.find(candidate => candidate.order_id === id)
    form.order_no_snapshot = item?.order_no || ''
    form.purchase_date = item?.purchase_date || form.purchase_date
    if (item?.amount_usd) form.affected_goods_value = Number(item.amount_usd)
  }
  async function searchProducts(keyword) {
    if (!keyword?.trim()) return
    const response = await searchAfterSalesProducts({ keyword })
    products.value = response.data?.items || []
  }
  function productChanged(id) {
    const item = products.value.find(candidate => candidate.product_id === id)
    form.product_name_snapshot = item?.product_name || ''
    if (item?.color) form.color_value = item.color
    if (item?.length) form.length_value = item.length
    const weight = String(item?.weight || '').match(/[\d.]+/)
    if (weight) form.weight_value = Number(weight[0])
  }
  function productModeChanged() {
    form.product_id = null; form.product_name_snapshot = ''; form.color_value = ''; form.length_value = ''
  }
  async function searchReviewers(keyword = '') {
    const response = await searchAfterSalesReviewers({ keyword })
    reviewers.value = response.data?.items || []
  }

  async function uploadEvidence(file, evidenceType) {
    if (isNew.value) await saveDraft({ silent: true })
    const response = await uploadAfterSalesEvidence(caseData.id, file, evidenceType)
    const item = response.data
    const result = { ...item, name: item.original_filename, path: item.original_filename, url: file.type.startsWith('image/') ? URL.createObjectURL(file) : '' }
    const detail = await getAfterSalesCase(caseData.id)
    Object.assign(caseData, detail.data)
    return result
  }
  async function removeEvidence(item) {
    await deleteAfterSalesEvidence(caseData.id, item.id)
    if (item.url?.startsWith('blob:')) URL.revokeObjectURL(item.url)
    const detail = await getAfterSalesCase(caseData.id)
    Object.assign(caseData, detail.data)
    msgSuccess('删除证据')
  }
  async function downloadEvidence(item) {
    const response = await downloadAfterSalesEvidence(item.id)
    const url = URL.createObjectURL(response.data)
    const anchor = document.createElement('a'); anchor.href = url; anchor.download = item.name; anchor.click()
    URL.revokeObjectURL(url)
  }

  async function analyze() {
    if (isNew.value || dirty.value) await saveDraft({ silent: true })
    analyzing.value = true
    await analyzeAfterSalesCase(caseData.id)
    clearInterval(pollTimer)
    let attempts = 0
    pollTimer = setInterval(async () => {
      attempts += 1
      await loadCase()
      if (!['ai_analyzing'].includes(caseData.current_status) || attempts >= 60) {
        clearInterval(pollTimer); pollTimer = null; analyzing.value = false
        if (caseData.current_status === 'awaiting_sales_decision') msgSuccess('AI 分析')
      }
    }, 3000)
  }

  function calculateDecision() {
    let total = 0
    let compensation = false
    actions.value.forEach(action => {
      let value = Number(AMOUNT_CODES.has(action.code) ? action.amount_usd : action.estimated_cost_usd || 0)
      if (['free_rework', 'resend'].includes(action.code)) value += Number(action.freight_cost_usd || 0)
      if (['return_inspection', 'paid_rework'].includes(action.code)) value = Number(action.freight_cost_usd || 0)
      const isValue = VALUE_CODES.has(action.code) || (['return_inspection', 'paid_rework'].includes(action.code) && action.freight_payer === 'company') || (action.code === 'custom' && action.company_bears_cost)
      if (isValue) { compensation = true; total += value }
    })
    caseData.has_compensation = compensation
    caseData.estimated_compensation_usd = total.toFixed(2)
  }

  async function saveDecision({ silent = false, validateForSubmit = false } = {}) {
    calculateDecision()
    if (!responsibilityClass.value) throw new Error('请选择责任判定')
    if (!actions.value.length) throw new Error('至少选择一项处理措施')
    if (validateForSubmit) {
      const actionError = validateActionDetails(actions.value)
      if (actionError) throw new Error(actionError)
    }
    const replyError = validateEnglishReply(caseData.has_compensation, replyDraft.value)
    if (replyError) throw new Error(replyError)
    if (latestAi.value && responsibilityClass.value !== latestAi.value.responsibility?.class && !overrideReason.value.trim()) throw new Error('修改 AI 责任判定时必须填写原因')
    const response = await saveAfterSalesDecision(caseData.id, {
      responsibility_class: responsibilityClass.value,
      responsibility_reason: responsibilityReason.value,
      responsibility_override_reason: overrideReason.value || null,
      actions: actions.value,
      customer_reply_draft: replyDraft.value,
      requires_return: actions.value.some(item => item.code === 'return_inspection'),
    })
    Object.assign(caseData, response.data)
    dirty.value = false
    if (!silent) msgSuccess('保存处理措施')
  }

  async function submit() {
    try {
      if (registrationDirty.value) await saveDraft({ silent: true })
      await saveDecision({ silent: true, validateForSubmit: true })
    } catch (error) { msgError(error.message); return }
    const response = await submitAfterSalesCase(caseData.id, { version: caseData.version, idempotency_key: crypto.randomUUID() })
    Object.assign(caseData, response.data); dirty.value = false
    msgSuccess(`提交审核，下一节点：${caseData.current_status === 'awaiting_supervisor' ? '直属主管' : '销售总监'}`)
    await loadCase()
  }

  async function review(decision) {
    let comment = '同意'
    if (decision !== 'approve') {
      try {
        const result = await ElMessageBox.prompt(decision === 'return' ? '请填写需要补充的内容' : '请填写拒绝原因', decision === 'return' ? '退回补充' : '拒绝售后方案', { inputValidator: value => Boolean(value?.trim()) || '原因不能为空' })
        comment = result.value
      } catch { return }
    } else if (caseData.has_compensation) {
      const title = caseData.current_status === 'awaiting_director' ? '赔偿终审确认' : '赔偿方案初审确认'
      try { await ElMessageBox.confirm(`确认批准预计赔偿 USD ${caseData.estimated_compensation_usd}？`, title, { type: 'warning' }) } catch { return }
    }
    let proxyReason = null
    if (isProxyReview.value) {
      const result = await ElMessageBox.prompt('请说明指定审批人无法处理的原因', '管理员代理审核', { inputValidator: value => Boolean(value?.trim()) || '代理原因不能为空' }).catch(() => null)
      if (!result) return
      proxyReason = result.value
    }
    const response = await reviewAfterSalesCase(caseData.id, { decision, comment, proxy_reason: proxyReason, version: caseData.version, idempotency_key: crypto.randomUUID() })
    Object.assign(caseData, response.data); msgSuccess('审核'); await loadCase()
  }

  async function requestEvidenceWaiver() {
    if (registrationDirty.value) await saveDraft({ silent: true })
    const result = await ElMessageBox.prompt('说明客户无法补充证据的原因，以及已完成的核实动作', '申请证据豁免', {
      inputType: 'textarea',
      inputValidator: value => (value?.trim().length >= 10) || '原因至少填写 10 个字',
    }).catch(() => null)
    if (!result) return
    const response = await requestAfterSalesEvidenceWaiver(caseData.id, {
      reason: result.value,
      version: caseData.version,
      idempotency_key: crypto.randomUUID(),
    })
    Object.assign(caseData, response.data)
    msgSuccess('证据豁免申请已提交直属主管')
    await loadCase()
  }

  async function reviewEvidenceWaiver(decision) {
    const title = decision === 'approve' ? '同意证据豁免' : '拒绝证据豁免'
    const result = await ElMessageBox.prompt('填写审核意见', title, {
      inputType: 'textarea',
      inputValidator: value => Boolean(value?.trim()) || '审核意见不能为空',
    }).catch(() => null)
    if (!result) return
    const response = await reviewAfterSalesEvidenceWaiver(caseData.id, {
      decision,
      comment: result.value,
      version: caseData.version,
      idempotency_key: crypto.randomUUID(),
    })
    Object.assign(caseData, response.data)
    msgSuccess(title)
    await loadCase()
  }

  async function transferApproval(newReviewerUserId, reason) {
    const response = await transferAfterSalesApproval(caseData.id, {
      new_reviewer_user_id: newReviewerUserId,
      reason,
      version: caseData.version,
      idempotency_key: crypto.randomUUID(),
    })
    Object.assign(caseData, response.data)
    msgSuccess('当前审批已转交')
    await loadCase()
  }
  async function retryNotification(notificationId) {
    await retryAfterSalesNotification(notificationId)
    msgSuccess('通知重试已执行')
    await loadCase()
  }

  async function withdraw() {
    const response = await withdrawAfterSalesCase(caseData.id, { version: caseData.version, idempotency_key: crypto.randomUUID() })
    Object.assign(caseData, response.data); msgSuccess('撤回'); await loadCase()
  }
  async function execute() {
    const result = await ElMessageBox.prompt('填写已经执行的措施、数量、交期或物流信息', '登记执行结果', { inputType: 'textarea', inputValidator: value => Boolean(value?.trim()) || '执行结果不能为空' }).catch(() => null)
    if (!result) return
    const response = await executeAfterSalesCase(caseData.id, { execution_result: result.value, customer_feedback: caseData.customer_feedback || null })
    Object.assign(caseData, response.data); msgSuccess('登记执行结果')
  }
  async function close() {
    const result = await ElMessageBox.prompt('记录客户确认或最终反馈', '关闭售后单', { inputType: 'textarea', inputValidator: value => Boolean(value?.trim()) || '客户反馈不能为空' }).catch(() => null)
    if (!result) return
    const response = await closeAfterSalesCase(caseData.id, { customer_feedback: result.value })
    Object.assign(caseData, response.data); msgSuccess('关闭售后单')
  }
  async function reopen() {
    const result = await ElMessageBox.prompt('说明重新打开原因', '重新打开售后单', {
      inputType: 'textarea', inputValidator: value => Boolean(value?.trim()) || '原因不能为空',
    }).catch(() => null)
    if (!result) return
    const response = await reopenAfterSalesCase(caseData.id, { reason: result.value })
    Object.assign(caseData, response.data); msgSuccess('重新打开售后单'); await loadCase()
  }
  async function copyReply() { await navigator.clipboard.writeText(replyDraft.value); msgSuccess('复制话术') }

  watch(form, () => {
    if (!hydrating.value) { dirty.value = true; registrationDirty.value = true }
  }, { deep: true, flush: 'sync' })
  watch([actions, replyDraft, responsibilityClass, responsibilityReason, overrideReason], () => {
    if (!hydrating.value) dirty.value = true
    calculateDecision()
  }, { deep: true, flush: 'sync' })
  watch(() => actions.value.map(item => item.code).join('|'), (next, previous) => {
    if (!hydrating.value && next && next !== previous) replyDraft.value = buildEnglishReply(actions.value)
  }, { flush: 'sync' })
  onBeforeRouteLeave(async () => {
    if (allowRouteLeave) return true
    if (!dirty.value || locked.value) return true
    try { await ElMessageBox.confirm('当前有未保存修改，仍要离开吗？', '未保存修改', { type: 'warning' }); return true } catch { return false }
  })
  onBeforeUnmount(() => { if (pollTimer) clearInterval(pollTimer); evidenceFiles.value.forEach(item => { if (item.url?.startsWith('blob:')) URL.revokeObjectURL(item.url) }) })

  return {
    loading, saving, analyzing, options, caseData, form, timeline, evidenceFiles, customers, orders, products, reviewers,
    actions, replyDraft, responsibilityClass, responsibilityReason, overrideReason, isNew, locked, latestAi, canReview,
    canReviewWaiver, canAdmin, currentUserId,
    initialize, saveDraft, searchCustomers, customerChanged, searchOrders, orderChanged, searchProducts, productChanged,
    productModeChanged, searchReviewers, uploadEvidence, removeEvidence, downloadEvidence, analyze, saveDecision, submit,
    review, requestEvidenceWaiver, reviewEvidenceWaiver, transferApproval, retryNotification, withdraw, execute, close, reopen, copyReply,
  }
}
