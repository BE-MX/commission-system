<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { portalAdminApi } from '@/api/portal'
import { downloadInvoiceExcel, downloadInvoicePdf } from '@/api/invoice'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { createAdminCommand } from './command.mjs'
import PiDocument from './PiDocument.vue'

const props = defineProps({ requestId: { type: String, required: true } })
const emit = defineEmits(['close', 'changed'])
const auth = useAuthStore()
const review = ref(null), loading = ref(false), error = ref(''), commandState = ref('idle'), tab = ref('current')
const errorSummary = ref(null), exporting = ref('')
const downloadUrls = new Set(), downloadTimers = new Set()
const draft = reactive({ action: '', reason: '', hours: null, confirmed: false })
const labels = { propose_pi: '发送 PI 修改提案', publish_pi: '发布已确认 PI', void_pi: '作废未流转 PI' }
const statuses = { current: '当前版本已发布', withdrawn: '已撤回，等待重新确认', pending_customer: '修改提案待客户确认', accepted: '客户已确认，等待发布', voided: '已作废', unavailable: '待核实' }
const command = createAdminCommand(value => portalAdminApi.command(value))
const locked = computed(() => ['sending', 'uncertain'].includes(commandState.value))
let sequence = 0, controller, disposed = false, errorSequence = 0
const message = e => e?.response?.data?.message || (e?.code === 'ERR_NETWORK' ? '网络连接中断，请按页面提示重试。' : e.message) || '暂时无法读取 PI，请重试。'
async function load() {
  if (locked.value) return
  const current = ++sequence
  exporting.value = ''
  controller?.abort(); controller = new AbortController()
  loading.value = true; review.value = null; error.value = ''; draft.action = ''; draft.confirmed = false
  try {
    const data = await portalAdminApi.piReview(props.requestId, controller.signal)
    if (current !== sequence) return
    review.value = data; draft.hours = data.policy.proposal_valid_hours[0] ?? null; draft.reason = ''; tab.value = 'current'
    command.clear(); commandState.value = 'idle'
  } catch (e) { if (current === sequence) void showError(message(e)) }
  finally { if (current === sequence) loading.value = false }
}
async function showError(value) {
  const current = ++errorSequence
  error.value = value
  await nextTick()
  if (!disposed && current === errorSequence && error.value === value) errorSummary.value?.$el?.focus()
}
watch(() => props.requestId, load, { immediate: true })
watch(() => [draft.action, draft.reason, draft.hours], () => { draft.confirmed = false })
function close() { if (!locked.value) emit('close') }
watch(() => [auth.accessToken, auth.user], () => { ++sequence; controller?.abort(); command.clear(); review.value = null; commandState.value = 'idle'; emit('close') })
function beforeUnload(event) { if (locked.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError('PI 操作结果待核对，请先重试原命令。'); return false } })
onBeforeUnmount(() => { downloadTimers.forEach(clearTimeout); downloadUrls.forEach(url => URL.revokeObjectURL(url)); disposed = true; ++sequence; controller?.abort(); command.clear(); window.removeEventListener('beforeunload', beforeUnload) })
function payload() {
  if (!review.value || !draft.confirmed || !review.value.available_actions.includes(draft.action)) throw new Error('请核对当前 PI 并确认可用操作。')
  if (draft.action === 'publish_pi') return { invoice_document_version: review.value.proposal.bound_invoice_document_version, accepted_revision_id: review.value.proposal.revision_id }
  const reason = draft.reason.trim()
  if (!reason || reason.length > 500) throw new Error('请填写 1–500 字的操作原因。')
  const body = { invoice_document_version: review.value.invoice_document_version, reason }
  if (draft.action === 'propose_pi') {
    if (!review.value.policy.proposal_valid_hours.includes(draft.hours)) throw new Error('请选择站点允许的提案有效期。')
    body.valid_for_hours = draft.hours
  }
  return body
}
async function exportCurrent(format) {
  if (!review.value || locked.value || exporting.value || tab.value !== 'current') return
  const current = sequence, invoice = review.value.invoice_id
  exporting.value = format
  try {
    const config = { showLoading: false, suppressToast: true, params: { template: 'leshine_pi' } }
    const response = await (format === 'pdf' ? downloadInvoicePdf(invoice, config) : downloadInvoiceExcel(invoice, config))
    if (disposed || current !== sequence || invoice !== review.value?.invoice_id) return
    const url = URL.createObjectURL(new Blob([response.data], { type: response.headers['content-type'] }))
    downloadUrls.add(url)
    const link = document.createElement('a')
    link.href = url; link.download = `${review.value.current_invoice.commercial_header.invoice_no || 'PI'}.${format === 'pdf' ? 'pdf' : 'xlsx'}`; link.click()
    const timer = setTimeout(() => { URL.revokeObjectURL(url); downloadUrls.delete(url); downloadTimers.delete(timer) }, 30000)
    downloadTimers.add(timer)
  } catch (e) { if (!disposed && current === sequence) void showError(message(e)) }
  finally { if (!disposed && current === sequence) exporting.value = '' }
}

async function submit(retry = false) {
  if (commandState.value === 'sending') return
  let value
  try { value = retry ? undefined : { id: props.requestId, action: draft.action, version: review.value.row_version, body: payload() } }
  catch (e) { void showError(message(e)); return }
  error.value = ''
  try {
    const promise = command.execute(value); commandState.value = command.state
    const result = await promise
    if (!result) return
    commandState.value = command.state
    msgSuccess(result.replayed ? '核对 PI 原操作回执' : labels[draft.action])
    emit('changed', props.requestId); emit('close')
  } catch (e) { commandState.value = command.state; void showError(message(e)) }
}
</script>

<template>
  <el-dialog :model-value="true" title="处理原 PI" width="1180px" top="4vh" class="portal-pi-dialog" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <p v-if="loading || commandState === 'sending'" role="status" class="pi-review-status">{{ loading ? '正在读取原 PI 条款…' : '正在提交 PI 操作，请等待回执…' }}</p>
    <div class="pi-review-content" v-loading="loading" :aria-busy="loading || commandState === 'sending' || undefined">
      <el-alert v-if="error" ref="errorSummary" id="portal-pi-error" tabindex="-1" :title="error" type="error" :closable="false" show-icon />
      <el-alert v-if="commandState === 'uncertain'" title="操作结果待核对。请重试原命令取得回执；不要关闭或刷新浏览器，也不要重新编辑并提交其他命令。" type="warning" :closable="false" show-icon />
      <template v-if="review">
        <header class="pi-review-hero"><div><p class="pi-customer-name" :title="review.customer.company_name">{{ review.customer.company_name }}</p><h2>{{ review.current_invoice.commercial_header.invoice_no }}</h2><div class="pi-version-meta"><span class="pi-state">{{ statuses[review.amendment_status] || '状态待核实' }}</span><span>文档版本 {{ review.invoice_document_version }}</span></div></div><div class="pi-hero-total"><span>当前 PI 总额</span><strong>{{ review.current_invoice.currency }} {{ review.current_invoice.total_amount ?? '待核实' }}</strong><section v-if="auth.hasPermission('invoice:read')" class="pi-export-section"><span class="pi-export-label">导出当前 PI</span><div class="pi-export-buttons"><GlassButton v-permission="'invoice:read'" left-icon="Download" :disabled="locked || !!exporting || tab !== 'current'" :loading="exporting === 'excel'" @click="exportCurrent('excel')">Excel</GlassButton><GlassButton v-permission="'invoice:read'" left-icon="Download" :disabled="locked || !!exporting || tab !== 'current'" :loading="exporting === 'pdf'" @click="exportCurrent('pdf')">PDF</GlassButton></div><p v-if="tab !== 'current'" class="pi-tab-note">切回「当前方舟 PI」后可导出，避免把历史快照当作当前版本。</p></section></div></header>
        <div class="pi-review-workspace"><div class="pi-review-documents">
        <el-tabs v-model="tab">
          <el-tab-pane label="当前方舟 PI" name="current"><PiDocument :document="review.current_invoice" live /></el-tab-pane>
          <el-tab-pane label="最近发布历史快照" name="published"><p>最近发布版本 {{ review.last_published.invoice_document_version }}；此处保留历史交易证据，不代表当前 PI 仍然有效。</p><PiDocument :document="review.last_published" /></el-tab-pane>
          <el-tab-pane v-if="review.proposal" label="客户修改提案" name="proposal"><p>{{ review.amendment_status === 'accepted' ? '客户已确认' : '等待客户确认' }} · 有效至 {{ formatBeijingDateTime(review.proposal.expires_at) }}{{ review.proposal.expired ? '（已过期）' : '' }}</p><PiDocument :document="review.proposal" /></el-tab-pane>
        </el-tabs>
        </div><aside class="pi-review-sidebar" aria-label="PI 版本与操作">

          <section class="pi-action-section"><h3>处理此 PI</h3><p class="pi-edit-guide">修改商品、金额或收货信息，请到发票管理编辑原 PI，保存后返回刷新。修改提案须经客户确认后发布。</p>
          <el-alert v-for="reason in review.blocked_reasons" :key="reason.code" :title="reason.message" type="warning" :closable="false" />
        <el-form label-position="top" :disabled="locked">
          <el-form-item label="本次 PI 操作"><el-radio-group v-model="draft.action"><el-radio-button v-for="action in review.available_actions" :key="action" v-permission="'invoice:write'" :value="action">{{ labels[action] }}</el-radio-button></el-radio-group><p v-if="!review.available_actions.length">当前没有可执行操作，请查看状态或联系当前负责人。</p></el-form-item>
          <el-alert v-if="draft.action === 'publish_pi'" title="将发布客户已确认的原 PI 版本，不生成第二张发票。服务器仍会复核实际内容、有效期与权限。" type="info" :closable="false" />
          <el-alert v-if="draft.action === 'void_pi'" title="作废会撤回客户下载并永久保留原 PI 与审计；本请求不能重新建票。已同步、已有回款、出库或其他处理中业务会阻止此操作。" type="warning" :closable="false" />
          <el-form-item v-if="draft.action === 'propose_pi'" label="提案有效期（小时）"><el-select v-model="draft.hours" aria-label="提案有效期（小时）"><el-option v-for="hours in review.policy.proposal_valid_hours" :key="hours" :value="hours" :label="String(hours)" /></el-select></el-form-item>
          <el-form-item v-if="draft.action && draft.action !== 'publish_pi'" label="操作原因"><el-input v-model="draft.reason" :aria-describedby="error ? 'portal-pi-error' : undefined" :aria-invalid="error && !draft.reason.trim() ? 'true' : undefined" type="textarea" maxlength="500" show-word-limit /></el-form-item>
          <el-checkbox v-if="draft.action" v-model="draft.confirmed">已核对原 PI、客户身份和当前条款，确认{{ labels[draft.action] }}</el-checkbox>
        </el-form></section>
        <details class="pi-identity"><summary>客户与归属标识</summary><dl><div><dt>客户名称</dt><dd>{{ review.customer.company_name }}</dd></div><div><dt>方舟客户</dt><dd>{{ review.customer.customer_id }}</dd></div><div><dt>OKKI 客户</dt><dd>{{ review.customer.okki_company_id }}</dd></div><div><dt>当前负责人</dt><dd>{{ review.customer.sales_user_id }}</dd></div><div><dt>原 PI 业务员</dt><dd>{{ review.customer.invoice_sales_user_id }}</dd></div></dl></details>
        </aside></div>
      </template>
    </div>
    <template #footer><GlassButton :disabled="locked" @click="close">关闭</GlassButton><GlassButton v-if="!locked" :disabled="loading" @click="load">刷新 PI</GlassButton><GlassButton v-if="commandState === 'uncertain'" v-permission="'invoice:write'" variant="primary" @click="submit(true)">重试原命令</GlassButton><GlassButton v-else v-permission="'invoice:write'" variant="primary" :loading="commandState === 'sending'" :disabled="!review || !draft.action || !draft.confirmed || loading" @click="submit()">确认 PI 操作</GlassButton></template>
  </el-dialog>
</template>
<style scoped>
.pi-review-content { height: 100%; min-height: 0; display: flex; flex-direction: column; }.pi-review-content > .el-alert { flex-shrink: 0; }
.pi-review-hero { display: flex; justify-content: space-between; gap: 24px; padding: 4px 0 24px; border-bottom: 1px solid var(--border-color); flex-shrink: 0; }
.pi-review-hero > div:first-child { min-width: 0; flex: 1; }.pi-customer-name { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; line-height: 1.65; margin: 0 0 6px; color: var(--text-secondary); font-size: 14px; }.pi-review-hero h2 { margin: 0 0 12px; font-size: 28px; line-height: 1.25; overflow-wrap: anywhere; }.pi-version-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; font-size: 13px; color: var(--text-secondary); }.pi-state { background: var(--toolbar-bg); border: 1px solid var(--border-color); border-radius: 6px; padding: 4px 8px; color: var(--text-primary); }.pi-hero-total { text-align: right; min-width: 160px; }.pi-hero-total span { display: block; color: var(--text-secondary); font-size: 13px; }.pi-hero-total strong { display: block; margin-top: 8px; font-size: 24px; font-variant-numeric: tabular-nums; line-height: 1.4; }
.pi-review-workspace { display: grid; grid-template-columns: minmax(0, 1fr) 280px; gap: 28px; flex: 1; min-height: 0; padding-top: 20px; }.pi-review-documents, .pi-review-sidebar { min-width: 0; overflow-y: auto; overscroll-behavior: contain; padding: 2px 6px 8px 2px; }.pi-review-sidebar { padding-left: 22px; border-left: 1px solid var(--border-color); }
h3 { margin: 0 0 10px; font-size: 16px; line-height: 1.4; }p { overflow-wrap: anywhere; font-size: 14px; line-height: 1.65; }.pi-export-section p, .pi-edit-guide { color: var(--text-secondary); margin: 0 0 14px; }.pi-export-buttons { display: flex; gap: 10px; }.pi-export-section { margin-top: 14px; }.pi-export-label { margin-bottom: 8px; }.pi-export-buttons { justify-content: flex-end; }.pi-hero-total .pi-tab-note { max-width: 250px; text-align: left; }.pi-tab-note { margin-top: 12px !important; font-size: 13px; }.el-alert { margin: 14px 0; }.el-form { margin-top: 16px; }.el-radio-group { display: grid; gap: 8px; }.el-checkbox { height: auto; white-space: normal; align-items: flex-start; margin-top: 12px; }.pi-identity { margin-top: 24px; font-size: 13px; color: var(--text-secondary); }.pi-identity summary { cursor: pointer; }.pi-identity dl div { display: flex; justify-content: space-between; gap: 12px; margin: 8px 0; }.pi-identity dd { margin: 0; min-width: 0; overflow-wrap: anywhere; text-align: right; }.pi-identity dt { flex-shrink: 0; }.pi-review-status { color: var(--text-secondary); }
@media (max-width: 800px) { .pi-review-content { height: auto; }.pi-review-workspace { display: block; }.pi-review-documents, .pi-review-sidebar { overflow: visible; padding: 0; }.pi-review-sidebar { border-left: 0; border-top: 1px solid var(--border-color); margin-top: 24px; padding-top: 24px; }.pi-review-hero { flex-direction: column; gap: 12px; }.pi-hero-total { text-align: left; }.pi-export-buttons { justify-content: flex-start; }.pi-hero-total strong { font-size: 22px; }.pi-review-hero h2 { font-size: 24px; } }
</style>
<style>
.portal-pi-dialog { max-width: calc(100vw - 24px); height: 88dvh; display: flex; flex-direction: column; margin-bottom: 0; }
.portal-pi-dialog .el-dialog__header, .portal-pi-dialog .el-dialog__footer { flex-shrink: 0; }.portal-pi-dialog .el-dialog__body { flex: 1; min-height: 0; overflow: hidden; }.portal-pi-dialog .el-dialog__footer { border-top: 1px solid var(--border-color); padding-top: 16px; display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 10px; }.portal-pi-dialog .el-dialog__footer .glass-button + .glass-button { margin-left: 0; }
.portal-pi-dialog .el-checkbox__label { white-space: normal; line-height: 1.65; }.portal-pi-dialog .el-radio-button__inner { width: 100%; border: 1px solid var(--border-color) !important; border-radius: 7px !important; text-align: left; padding: 12px; white-space: normal; line-height: 1.5; box-shadow: none !important; }.portal-pi-dialog .el-radio-button { width: 100%; }.portal-pi-dialog .el-tabs__item { font-size: 14px; }.portal-pi-dialog .el-tabs__content { overflow: visible; }
@media (max-width: 800px) { .portal-pi-dialog { height: 92dvh; margin-top: 4dvh; }.portal-pi-dialog .el-dialog__body { overflow-y: auto; }.portal-pi-dialog .el-dialog__footer { gap: 8px; } }
</style>
