<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { portalAdminApi } from '@/api/portal'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { createAdminCommand } from './command.mjs'
import ReviewSnapshot from './ReviewSnapshot.vue'
import ProposalCatalogPicker from './ProposalCatalogPicker.vue'
import ProposalPreview from './ProposalPreview.vue'
import { proposalLine, validateProposalPreview } from './proposalPreparation.mjs'

const props = defineProps({ requestId: { type: String, default: '' } })
const emit = defineEmits(['close', 'changed'])
const auth = useAuthStore()
const review = ref(null), loading = ref(false), error = ref(''), commandState = ref('idle')
const draft = reactive({ action: '', reason: '', items: [], fees: {}, delivery: {}, payment_terms: '', valid_for_hours: null, remark: '', confirmed: false })
const deliveryFields = { contact_name: ['联系人', 100], phone: ['电话', 40], address_line1: ['地址', 200], address_line2: ['补充地址', 200], city: ['城市', 100], region: ['省 / 州', 100], postal_code: ['邮编', 32], country_code: ['国家代码（两位大写）', 2] }
const feeFields = { shipping_amount: '运费', packaging_amount: '包装费', surcharge_amount: '附加费' }
const actionLabels = { propose: '发送确认提案', approve: '审核并生成正式 PI', reject: '拒绝请求' }
const command = createAdminCommand(value => portalAdminApi.command(value))
const preview = ref(null), previewLoading = ref(false), pickerVisible = ref(false), errorSummary = ref(null)
const feeAmountPattern = /^(0|[1-9][0-9]{0,11})\.[0-9]{2}$/
const locked = computed(() => loading.value || previewLoading.value || ['sending', 'uncertain'].includes(commandState.value))
let previewSequence = 0, previewController, previewBody = ''
let sequence = 0, controller, disposed = false, errorSequence = 0
const message = e => e?.response?.data?.message || e.message || '读取失败，请重试。'
async function load() {
  if (!props.requestId || locked.value) return
  const current = ++sequence
  controller?.abort(); controller = new AbortController()
  clearPreview(); pickerVisible.value = false
  loading.value = true; error.value = ''; review.value = null; draft.action = ''; draft.confirmed = false
  try {
    const data = await portalAdminApi.review(props.requestId, controller.signal)
    if (current !== sequence) return
    review.value = data
    const order = data.order
    const rules = new Map((data.quantity_rules || []).map(row => [row.item_id, row]))
    Object.assign(draft, { action: '', reason: '', confirmed: false,
      items: order.items.map(line => ({ item_id: line.display_snapshot.item_id, quantity: line.quantity, min_order_qty: rules.has(line.display_snapshot.item_id) ? Math.ceil(rules.get(line.display_snapshot.item_id).min_order_qty / rules.get(line.display_snapshot.item_id).step_qty) * rules.get(line.display_snapshot.item_id).step_qty : null, step_qty: rules.get(line.display_snapshot.item_id)?.step_qty, unavailable: !rules.has(line.display_snapshot.item_id), label: `${line.display_snapshot.model_name} / ${line.display_snapshot.color_name} / ${line.display_snapshot.length} / ${line.display_snapshot.weight}` })),
      fees: { shipping_amount: order.fees?.shipping_amount ?? '', packaging_amount: order.fees?.packaging_amount ?? '', surcharge_amount: order.fees?.surcharge_amount ?? '', surcharge_name: order.fees?.surcharge_name || '' },
      delivery: structuredClone(order.delivery), remark: order.remark || '',
      payment_terms: order.payment_terms_snapshot?.code || data.policy.default_payment_term_code || '',
      valid_for_hours: data.policy.proposal_valid_hours[0] })
    command.clear(); commandState.value = 'idle'
  } catch (e) { if (current === sequence) void showError(message(e)) }
  finally { if (current === sequence) loading.value = false }
}
watch(() => props.requestId, load, { immediate: true })
async function showError(value) {
  const current = ++errorSequence
  error.value = value
  await nextTick()
  if (!disposed && current === errorSequence && error.value === value) errorSummary.value?.$el?.focus()
}
watch(() => [draft.action, draft.reason, draft.items, draft.fees, draft.delivery, draft.payment_terms, draft.valid_for_hours, draft.remark], () => {
  draft.confirmed = false; clearPreview()
}, { deep: true, flush: 'sync' })
function clearPreview() { previewSequence++; previewController?.abort(); preview.value = null; previewBody = ''; previewLoading.value = false }
function addItem(item) {
  if (locked.value) return
  try { draft.items.push(proposalLine(item, draft.items)); error.value = '' } catch (e) { void showError(message(e)) }
}
async function previewProposal() {
  if (locked.value || draft.action !== 'propose') return
  let body
  try { body = payload(false) } catch (e) { void showError(message(e)); return }
  clearPreview(); draft.confirmed = false; error.value = ''
  const current = ++previewSequence, requestId = props.requestId, version = review.value.order.row_version
  previewController = new AbortController(); previewLoading.value = true
  try {
    const result = await portalAdminApi.previewProposal(requestId, version, body, previewController.signal)
    if (current !== previewSequence) return
    preview.value = validateProposalPreview(result, requestId, version, body, review.value.order.currency)
    previewBody = JSON.stringify(body)
  } catch (e) {
    if (current === previewSequence) {
      void showError(message(e))
      if ([401, 403].includes(e?.response?.status)) invalidate()
    }
  } finally { if (current === previewSequence) previewLoading.value = false }
}
function catalogDenied() {
  if (['sending', 'uncertain'].includes(commandState.value)) {
    pickerVisible.value = false; review.value = null; clearPreview()
    void showError('目录读取权限已变化，详情已隐藏。原提案结果仍待核对，请重试原命令获取回执。')
    return
  }
  invalidate()
}
function close() { if (!locked.value) emit('close') }
function invalidate() { ++sequence; controller?.abort(); clearPreview(); command.clear(); commandState.value = 'idle'; review.value = null; emit('close') }
watch(() => [auth.accessToken, auth.user], invalidate)
function beforeUnload(event) { if (locked.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError('当前操作结果待核对，请先重试原命令。'); return false } })
onBeforeUnmount(() => { disposed = true; ++sequence; controller?.abort(); clearPreview(); command.clear(); window.removeEventListener('beforeunload', beforeUnload) })
function payload(requireConfirmation = true) {
  if (requireConfirmation && !draft.confirmed) throw new Error('请确认本次操作内容。')
  if (!review.value.available_actions.includes(draft.action)) throw new Error('当前操作不可用，请刷新。')
  if (draft.action === 'approve') return { accepted_revision_id: review.value.order.proposal.revision_id }
  const reason = draft.reason.trim()
  if (!reason || reason.length > 500) throw new Error('请填写 1–500 字的操作原因。')
  if (draft.action === 'reject') return { reason }
  if (draft.items.some(line => line.unavailable)) throw new Error('部分原商品已下架或授权失效，请移除后重新预览。')
  if (draft.items.some(line => line.min_order_qty && (line.quantity < line.min_order_qty || line.quantity % line.step_qty !== 0))) throw new Error('请按商品当前起订量和步长填写数量。')
  if (new Set(draft.items.map(line => line.item_id)).size !== draft.items.length) throw new Error('同一商品不能重复。')
  if (!draft.items.length || draft.items.length > 100 || draft.items.some(line => !line.item_id || !Number.isInteger(line.quantity) || line.quantity < 1 || line.quantity > 10000)) throw new Error('请保留 1–100 行商品，数量须为 1–10000 的整数。')
  if (Object.keys(feeFields).some(key => !feeAmountPattern.test(draft.fees[key]))) throw new Error('请明确填写每项费用，保留两位小数；无费用时填写 0.00。')
  if (draft.fees.surcharge_amount !== '0.00' && !draft.fees.surcharge_name.trim()) throw new Error('请填写附加费名称。')
  if (!review.value.policy.payment_terms.some(term => term.code === draft.payment_terms) || !review.value.policy.proposal_valid_hours.includes(draft.valid_for_hours)) throw new Error('请选择站点允许的付款条件与有效期。')
  return { items: draft.items.map(({ item_id, quantity }) => ({ item_id, quantity })), fees: { ...draft.fees }, delivery: { ...draft.delivery }, customer_po: review.value.order.customer_po || '', remark: draft.remark, payment_terms: draft.payment_terms, valid_for_hours: draft.valid_for_hours, reason }
}
async function submit(retry = false) {
  if (commandState.value === 'sending' || previewLoading.value || loading.value) return

  let value
  try {
    if (!retry && draft.action === 'propose' && (!preview.value || previewBody !== JSON.stringify(payload(false)))) throw new Error('请先预览当前提案并核对变化。')
    value = retry ? undefined : { id: props.requestId, action: draft.action, version: review.value.order.row_version, body: payload() }
  }
  catch (e) { void showError(message(e)); return }
  error.value = ''
  try {
    const promise = command.execute(value)
    commandState.value = command.state
    const receipt = await promise
    if (!receipt) return
    commandState.value = command.state
    msgSuccess(receipt.replayed ? '核对原操作回执' : '处理请求')
    emit('changed', props.requestId)
    emit('close')
  } catch (e) { commandState.value = command.state; void showError(message(e)) }
}
</script>

<template>
  <el-dialog :model-value="!!requestId" title="处理客户下单请求" width="760px" class="portal-review-dialog" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <p v-if="loading || previewLoading || commandState === 'sending'" class="review-status" role="status">{{ loading ? '正在读取当前请求条款…' : previewLoading ? '正在核验当前价格和库存…' : '正在提交操作，请等待回执…' }}</p>
    <div v-loading="loading" :aria-busy="loading || previewLoading || commandState === 'sending' || undefined">
      <el-alert v-if="error" ref="errorSummary" id="portal-review-error" tabindex="-1" :title="error" type="error" :closable="false" show-icon />
      <el-alert v-if="commandState === 'uncertain'" title="操作结果待核对。请重试原命令获取持久回执；页面当前状态不能证明本次操作成功。请勿关闭或刷新浏览器。" type="warning" :closable="false" show-icon />
      <template v-if="review">
        <p><strong>{{ review.order.request_no }}</strong> · 客户 PO：{{ review.order.customer_po || '未填写' }}</p>
        <p v-if="review.order.proposal">客户{{ review.order.proposal.accepted ? '已确认' : '尚未确认' }}当前提案 · 有效至 {{ formatBeijingDateTime(review.order.proposal.expires_at) }}</p>
        <p>当前快照总额：{{ review.order.currency }} {{ review.order.total_amount ?? '费用待确认' }}</p>
        <ReviewSnapshot :order="review.order" :customer="review.customer" :standards="review.standard_lines" />
        <el-empty v-if="!review.available_actions.length" description="当前没有可执行操作。可能仍待客户确认、已建票或功能未启用。" />
        <el-form v-else label-position="top" :disabled="locked">
          <el-form-item label="本次操作"><el-radio-group v-model="draft.action">
            <el-radio-button v-for="action in review.available_actions" :key="action" v-permission="action === 'approve' ? 'invoice:write' : 'portal_order:write'" :value="action">{{ actionLabels[action] }}</el-radio-button>
          </el-radio-group></el-form-item>
          <template v-if="draft.action === 'propose'">
            <el-alert title="提案发送时由服务器按当前合同价和库存重新校验。客户必须确认完整的新条款，才能审核生成 PI。" type="info" :closable="false" />
            <GlassButton :disabled="locked" @click="pickerVisible = !pickerVisible">{{ pickerVisible ? '收起授权目录' : '新增授权商品' }}</GlassButton>
            <ProposalCatalogPicker v-if="pickerVisible" :key="`${requestId}:${review.order.row_version}`" :request-id="requestId" :version="review.order.row_version" :selected="draft.items" :disabled="locked" @add="addItem" @denied="catalogDenied" />
            <div v-for="(line, index) in draft.items" :key="line.item_id" class="proposal-line"><span>{{ line.label }}<br><small>{{ line.unavailable ? '已下架或未授权，请移除' : `起订 ${line.min_order_qty} · 步长 ${line.step_qty}` }}</small></span><el-input-number :disabled="locked || line.unavailable" v-model="line.quantity" :min="line.min_order_qty || 1" :step="line.step_qty || 1" :step-strictly="!!line.step_qty" :max="10000" :precision="0" aria-label="商品数量" /><GlassButton variant="link" :disabled="locked" @click="draft.items.splice(index, 1)">移除</GlassButton></div>
            <div class="form-grid"><el-form-item v-for="(label, key) in feeFields" :key="key" :label="`${label}（${review.order.currency}）`"><el-input v-model="draft.fees[key]" :aria-describedby="error ? 'portal-review-error' : undefined" :aria-invalid="error && !feeAmountPattern.test(draft.fees[key]) ? 'true' : undefined" inputmode="decimal" placeholder="0.00" maxlength="15" /></el-form-item><el-form-item label="附加费名称"><el-input v-model="draft.fees.surcharge_name" maxlength="100" /></el-form-item></div>
            <div class="form-grid"><el-form-item label="付款条件"><el-select v-model="draft.payment_terms"><el-option v-for="term in review.policy.payment_terms" :key="term.code" :value="term.code" :label="term.display_text" /></el-select></el-form-item><el-form-item label="有效期（小时）"><el-select v-model="draft.valid_for_hours"><el-option v-for="hours in review.policy.proposal_valid_hours" :key="hours" :value="hours" :label="String(hours)" /></el-select></el-form-item></div>
            <h3>收货信息</h3><div class="form-grid"><el-form-item v-for="([label, limit], key) in deliveryFields" :key="key" :label="label"><el-input v-model="draft.delivery[key]" :maxlength="limit" /></el-form-item></div>
            <el-form-item label="订单备注"><el-input v-model="draft.remark" type="textarea" maxlength="1000" show-word-limit /></el-form-item>
          </template>
          <el-alert v-if="draft.action === 'approve'" title="将按客户已确认的版本创建正式 PI。服务器会再次校验权限、价格、库存及有效期；PI 不代表锁货或收款。" type="warning" :closable="false" />
          <el-alert v-if="draft.action === 'reject'" title="拒绝后本请求不能继续建票。原请求和操作原因将保留。" type="warning" :closable="false" />
          <el-form-item v-if="draft.action && draft.action !== 'approve'" label="操作原因"><el-input v-model="draft.reason" :aria-describedby="error ? 'portal-review-error' : undefined" :aria-invalid="error && !draft.reason.trim() ? 'true' : undefined" type="textarea" maxlength="500" show-word-limit /></el-form-item>
          <template v-if="draft.action === 'propose'"><GlassButton :disabled="locked" :loading="previewLoading" @click="previewProposal">预览金额与变化</GlassButton><ProposalPreview v-if="preview" :preview="preview" /><p v-else class="preview-hint">请先填写完整条款及原因，再预览核价。编辑任何内容后需要重新预览。</p></template>
          <el-checkbox v-if="draft.action" v-model="draft.confirmed" :disabled="locked || (draft.action === 'propose' && !preview)">我已核对内容，确认{{ actionLabels[draft.action] }}</el-checkbox>
        </el-form>
      </template>
    </div>
    <template #footer><GlassButton :disabled="locked" @click="close">关闭</GlassButton><GlassButton v-if="!locked" :disabled="loading" @click="load">刷新状态</GlassButton><GlassButton v-if="commandState === 'uncertain'" v-permission="'portal_order:write'" variant="primary" @click="submit(true)">重试原命令</GlassButton><GlassButton v-else v-permission="'portal_order:write'" variant="primary" :loading="commandState === 'sending'" :disabled="locked || !review || !draft.action || !draft.confirmed || (draft.action === 'propose' && !preview)" @click="submit()">确认操作</GlassButton></template>
  </el-dialog>
</template>

<style scoped>
.el-alert { margin-bottom: 16px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.proposal-line { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin: 16px 0; }
.proposal-line span { flex: 1; min-width: 160px; overflow-wrap: anywhere; }
.el-select { width: 100%; }
.review-status { color: var(--text-secondary); line-height: 1.6; }
.preview-hint { color: var(--text-secondary); line-height: 1.6; }
.el-checkbox { height: auto; white-space: normal; }
@media (max-width: 600px) { .form-grid { grid-template-columns: 1fr; } }
</style>
<style>.portal-review-dialog { max-width: calc(100vw - 24px); } .portal-review-dialog .el-checkbox__label { white-space: normal; line-height: 1.6; }</style>
