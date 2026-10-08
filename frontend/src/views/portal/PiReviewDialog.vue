<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { portalAdminApi } from '@/api/portal'
import { useAuthStore } from '@/stores/auth'
import { msgError, msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { createAdminCommand } from './command.mjs'
import PiDocument from './PiDocument.vue'

const props = defineProps({ requestId: { type: String, required: true } })
const emit = defineEmits(['close', 'changed'])
const auth = useAuthStore()
const review = ref(null), loading = ref(false), error = ref(''), commandState = ref('idle'), tab = ref('current')
const errorSummary = ref(null)
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
onBeforeUnmount(() => { disposed = true; ++sequence; controller?.abort(); command.clear(); window.removeEventListener('beforeunload', beforeUnload) })
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
  <el-dialog :model-value="true" title="处理原 PI" width="760px" class="portal-pi-dialog" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <p v-if="loading || commandState === 'sending'" role="status" class="pi-review-status">{{ loading ? '正在读取原 PI 条款…' : '正在提交 PI 操作，请等待回执…' }}</p>
    <div v-loading="loading" :aria-busy="loading || commandState === 'sending' || undefined">
      <el-alert v-if="error" ref="errorSummary" id="portal-pi-error" tabindex="-1" :title="error" type="error" :closable="false" show-icon />
      <el-alert v-if="commandState === 'uncertain'" title="操作结果待核对。请重试原命令取得回执；不要关闭或刷新浏览器，也不要重新编辑并提交其他命令。" type="warning" :closable="false" show-icon />
      <template v-if="review">
        <h3>{{ review.current_invoice.commercial_header.invoice_no }} · {{ statuses[review.amendment_status] || '状态待核实' }}</h3>
        <p>{{ review.customer.company_name }} · 方舟客户 {{ review.customer.customer_id }} / OKKI {{ review.customer.okki_company_id }}</p>
        <p>当前负责人 {{ review.customer.sales_user_id }} · 原 PI 业务员 {{ review.customer.invoice_sales_user_id }} · PI 文档版本 {{ review.invoice_document_version }}</p>
        <el-alert v-for="reason in review.blocked_reasons" :key="reason.code" :title="reason.message" type="warning" :closable="false" />
        <el-alert title="需调整内容时，请在方舟发票管理中编辑这张原 PI，保存后返回刷新。发送修改提案后由客户重新确认，再发布该版本。" type="info" :closable="false" />
        <el-tabs v-model="tab">
          <el-tab-pane label="当前方舟 PI" name="current"><PiDocument :document="review.current_invoice" live /></el-tab-pane>
          <el-tab-pane label="最近发布历史快照" name="published"><p>最近发布版本 {{ review.last_published.invoice_document_version }}；此处保留历史交易证据，不代表当前 PI 仍然有效。</p><PiDocument :document="review.last_published" /></el-tab-pane>
          <el-tab-pane v-if="review.proposal" label="客户修改提案" name="proposal"><p>{{ review.amendment_status === 'accepted' ? '客户已确认' : '等待客户确认' }} · 有效至 {{ formatBeijingDateTime(review.proposal.expires_at) }}{{ review.proposal.expired ? '（已过期）' : '' }}</p><PiDocument :document="review.proposal" /></el-tab-pane>
        </el-tabs>
        <el-form label-position="top" :disabled="locked">
          <el-form-item label="本次 PI 操作"><el-radio-group v-model="draft.action"><el-radio-button v-for="action in review.available_actions" :key="action" v-permission="'invoice:write'" :value="action">{{ labels[action] }}</el-radio-button></el-radio-group><p v-if="!review.available_actions.length">当前没有可执行操作，请查看状态或联系当前负责人。</p></el-form-item>
          <el-alert v-if="draft.action === 'publish_pi'" title="将发布客户已确认的原 PI 版本，不生成第二张发票。服务器仍会复核实际内容、有效期与权限。" type="info" :closable="false" />
          <el-alert v-if="draft.action === 'void_pi'" title="作废会撤回客户下载并永久保留原 PI 与审计；本请求不能重新建票。已同步、已有回款、出库或其他处理中业务会阻止此操作。" type="warning" :closable="false" />
          <el-form-item v-if="draft.action === 'propose_pi'" label="提案有效期（小时）"><el-select v-model="draft.hours" aria-label="提案有效期（小时）"><el-option v-for="hours in review.policy.proposal_valid_hours" :key="hours" :value="hours" :label="String(hours)" /></el-select></el-form-item>
          <el-form-item v-if="draft.action && draft.action !== 'publish_pi'" label="操作原因"><el-input v-model="draft.reason" :aria-describedby="error ? 'portal-pi-error' : undefined" :aria-invalid="error && !draft.reason.trim() ? 'true' : undefined" type="textarea" maxlength="500" show-word-limit /></el-form-item>
          <el-checkbox v-if="draft.action" v-model="draft.confirmed">已核对原 PI、客户身份和当前条款，确认{{ labels[draft.action] }}</el-checkbox>
        </el-form>
      </template>
    </div>
    <template #footer><GlassButton :disabled="locked" @click="close">关闭</GlassButton><GlassButton v-if="!locked" :disabled="loading" @click="load">刷新 PI</GlassButton><GlassButton v-if="commandState === 'uncertain'" v-permission="'invoice:write'" variant="primary" @click="submit(true)">重试原命令</GlassButton><GlassButton v-else v-permission="'invoice:write'" variant="primary" :loading="commandState === 'sending'" :disabled="!review || !draft.action || !draft.confirmed || loading" @click="submit()">确认 PI 操作</GlassButton></template>
  </el-dialog>
</template>
<style scoped>
.el-alert { margin: 16px 0; } h3 { font-size: 16px; } p { overflow-wrap: anywhere; } .pi-review-status { color: var(--text-secondary); line-height: 1.6; }
.el-form { margin-top: 20px; } .el-radio-group { flex-wrap: wrap; gap: 4px 0; }
.el-checkbox { height: auto; white-space: normal; align-items: flex-start; }
</style>
<style>.portal-pi-dialog { max-width: calc(100vw - 24px); } .portal-pi-dialog .el-checkbox__label { white-space: normal; }</style>
