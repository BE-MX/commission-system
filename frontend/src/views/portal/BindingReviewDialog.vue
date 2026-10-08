<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import { msgError, msgSuccess } from '@/utils/feedback'
import { createAccessMutation } from './customerAccess.mjs'
import { bindingReviewPayload, validateBindingReceipt } from './bindingReview.mjs'
const props = defineProps({ access: { type: Object, required: true } }), emit = defineEmits(['close', 'changed', 'denied'])
const auth = useAuthStore(), data = ref(null), loading = ref(false), error = ref(''), notice = ref(''), state = ref('idle'), confirmed = ref(false), orderPage = ref(1)
const form = reactive({ action: 'transfer', assignment_id: '', identity_id: '', pending_request_ids: [], history_policy: 'remove', history_days: null, reason: '' })
const mutation = createAccessMutation(async operation => validateBindingReceipt(operation, await portalAdminApi.bindingMutation(operation)))
const locked = computed(() => loading.value || ['sending', 'uncertain'].includes(state.value))
const pendingRows = computed(() => data.value?.pending_requests.slice((orderPage.value - 1) * 20, orderPage.value * 20) || [])
const pendingStatuses = { submitted: '待业务员处理', awaiting_customer: '待客户确认', ready_for_review: '待业务员审核' }
let generation = 0, sequence = 0, controller, disposed = false, feedbackSequence = 0
const denied = ref(false), errorSummary = ref(null), noticeSummary = ref(null)
const message = e => e?.response?.data?.message || (e?.code === 'ERR_NETWORK' ? '网络连接中断，请按页面提示核对。' : e?.message) || '复核读取失败。'

async function showFeedback(value, isNotice = false) {
  const current = ++feedbackSequence, identity = generation
  const text = isNotice ? notice : error, target = isNotice ? noticeSummary : errorSummary
  text.value = value
  await nextTick()
  if (!disposed && current === feedbackSequence && identity === generation && text.value === value) target.value?.$el?.focus()
}
function hideDenied(e) {
  if (![401, 403, 404].includes(typeof e === 'number' ? e : e?.response?.status)) return
  denied.value = true; ++sequence; controller?.abort(); loading.value = false; data.value = null; notice.value = ''
  resetForm()
  // Keep the original in-flight/unknown mutation for GET inspection; never resend it.
  emit('denied')
}
watch(form, () => { confirmed.value = false }, { deep: true, flush: 'sync' })
function resetForm() { Object.assign(form, { assignment_id: '', identity_id: '', pending_request_ids: [], history_policy: 'remove', history_days: null, reason: '' }); confirmed.value = false; orderPage.value = 1 }
function clear() { generation++; sequence++; feedbackSequence++; controller?.abort(); mutation.clear(); data.value = null; state.value = 'idle'; loading.value = false; resetForm() }
async function load(recovery = false) {
  if (state.value === 'sending' || loading.value) return
  const identity = generation, request = ++sequence; controller?.abort(); controller = new AbortController(); loading.value = true; error.value = ''; notice.value = ''; ++feedbackSequence
  try {
    const result = await portalAdminApi.bindingReview(props.access.id, controller.signal)
    if (identity !== generation || request !== sequence) return
    if (result.access_id !== props.access.id || !Array.isArray(result.pending_requests)) throw new Error('复核上下文不完整。')
    denied.value = false; data.value = result; resetForm(); mutation.clear(); state.value = 'idle'
    if (recovery) { const text = '已读取当前绑定与影响范围并放弃草稿，不能据此确认原操作成功；本次未重发写入。'; void showFeedback(text, true); emit('changed', text) }
  } catch (e) {
    if (identity === generation && request === sequence) {
      hideDenied(e); void showFeedback(message(e)); if (state.value !== 'uncertain') data.value = null
    }
  } finally { if (identity === generation && request === sequence) loading.value = false }
}
function selectOrder(id, checked) {
  if (locked.value) return
  form.pending_request_ids = checked ? [...new Set([...form.pending_request_ids, id])] : form.pending_request_ids.filter(value => value !== id)
}
async function save() {
  if (locked.value || denied.value || !confirmed.value || !data.value) return
  let body
  try { body = bindingReviewPayload(data.value, form) } catch (e) { void showFeedback(message(e)); return }
  const identity = generation, action = form.action
  try {
    const promise = mutation.execute({ action, id: props.access.id, version: data.value.row_version, body }); state.value = mutation.state; error.value = ''; notice.value = ''; ++feedbackSequence
    const result = await promise
    if (identity !== generation || !result) return
    state.value = mutation.state; msgSuccess('保存客户复核')
    const detail = action === 'transfer' ? `已交接 ${result.reassigned_request_ids.length} 个待处理请求，未交接 ${result.unassigned_pending_request_ids.length} 个；向新负责人授予 ${result.history_grants} 条历史读取。` : `已更新公司身份，失效报价 ${result.expired_quotes} 份。`
    emit('changed', `${detail}${result.status === 'review_required' ? '身份仍待复核。' : '客户已暂停，请核对后另行启用。'}历史订单和 PI 归属未重写。`); emit('close')
  } catch (e) { if (identity === generation) { state.value = mutation.state; hideDenied(e); void showFeedback(message(e)) } }
}
function close() { if (!locked.value) emit('close') }
function beforeUnload(e) { if (locked.value) { e.preventDefault(); e.returnValue = '' } }
watch(() => [auth.accessToken, auth.user], () => { clear(); emit('close') })
window.addEventListener('beforeunload', beforeUnload)
onBeforeRouteLeave(() => { if (locked.value) { msgError('请先核对客户复核结果。'); return false } })
onBeforeUnmount(() => { disposed = true; clear(); window.removeEventListener('beforeunload', beforeUnload) })
onMounted(() => load())
</script>

<template>
  <el-dialog :model-value="true" :title="denied ? '归属与身份复核 · 权限需要核对' : `归属与身份复核 · ${access.company_display_name}`" width="980px" class="portal-binding-review" :close-on-click-modal="false" :close-on-press-escape="!locked" :show-close="!locked" @update:model-value="value => { if (!value) close() }">
    <div v-loading="loading" class="review-content" :aria-busy="loading || state === 'sending' || undefined">
      <p v-if="loading || state === 'sending'" role="status">{{ loading ? '正在读取当前绑定与影响范围…' : '正在提交客户复核，请等待回执…' }}</p>
      <el-alert v-if="error" ref="errorSummary" id="portal-binding-review-error" tabindex="-1" :title="error" type="error" :closable="false" /><el-alert v-if="notice" ref="noticeSummary" tabindex="-1" :title="notice" type="info" :closable="false" /><el-alert v-if="state === 'uncertain'" title="操作结果未知，当前复核已冻结。仅重新读取当前状态核对，不重发转交或重绑。" type="warning" :closable="false" />
      <template v-if="data"><p>当前负责人 {{ data.current_sales_user_id }} · 当前 OKKI 公司 {{ data.current_company_id }} · 已有订单 {{ data.order_total }} 份（关联 PI {{ data.invoice_order_total }} 份）</p>
        <el-alert title="以下操作会撤销现有登录和未使用邀请，使旧报价失效；完成后暂停客户或继续要求复核，须另行启用。历史归属和 PI 不重写。" type="warning" :closable="false" />
        <el-form label-position="top" :disabled="locked" :aria-describedby="error ? 'portal-binding-review-error' : undefined">
          <el-radio-group v-model="form.action"><el-radio-button value="transfer">复核负责人转交</el-radio-button><el-radio-button value="rebind">重绑外部公司身份</el-radio-button></el-radio-group>
          <template v-if="form.action === 'transfer'">
            <p>新负责人必须先在方舟客户档案中设为有效主负责人。这里仅同步门户授权，并处理明确选中的待办。</p>
            <el-form-item label="新主负责人"><el-select v-model="form.assignment_id" aria-label="新主负责人" placeholder="明确选择有效归属"><el-option v-for="row in data.assignments" :key="row.id" :label="`${row.sales_name || row.sales_user_id} · 归属 ${row.id}`" :value="row.id" /></el-select></el-form-item>
            <el-alert v-if="data.pending_truncated" :title="`共有 ${data.pending_total} 个待处理请求，此处仅列前 1000 个。未列出及未勾选请求均不会交接。`" type="warning" :closable="false" />
            <h3>选择交接的未建票请求</h3><p>已选 {{ form.pending_request_ids.length }} 个，未交接 {{ data.pending_total - form.pending_request_ids.length }} 个；选中请求回到待处理，必须重新提案并取得客户确认。</p>
            <el-table :scrollbar-tabindex="0" :data="pendingRows" border class="list-table" empty-text="没有可交接的未建票请求"><el-table-column label="交接" min-width="80"><template #default="{ row }"><el-checkbox :model-value="form.pending_request_ids.includes(row.id)" :disabled="locked" :aria-label="`交接 ${row.public_no}`" @change="value => selectOrder(row.id, value)" /></template></el-table-column><el-table-column prop="public_no" label="请求编号" min-width="200" /><el-table-column label="当前状态" min-width="180"><template #default="{ row }">{{ pendingStatuses[row.status] || '状态待核实' }}</template></el-table-column><el-table-column prop="servicing_user_id" label="当前服务人" min-width="130" /></el-table>
            <el-pagination :disabled="locked" v-model:current-page="orderPage" :page-size="20" :total="data.pending_requests.length" layout="total, prev, pager, next" />
            <el-form-item label="历史读取策略"><el-radio-group v-model="form.history_policy"><el-radio-button value="remove">不新增历史读取</el-radio-button><el-radio-button value="explicit_grant">向新负责人限时授权</el-radio-button></el-radio-group></el-form-item>
            <p>旧历史授权全部撤销。限时授权仅给新负责人，覆盖本次已有且未选中交接的 {{ data.order_total - form.pending_request_ids.length }} 条订单，不包括未来订单；未交接待办即使可读也不会自动获得处理权。</p>
            <el-form-item v-if="form.history_policy === 'explicit_grant'" label="历史读取有效天数"><el-input-number v-model="form.history_days" aria-label="历史读取有效天数" :min="1" :max="365" :precision="0" /></el-form-item>
          </template>
          <template v-else><el-alert v-if="data.requires_assignment_review || data.customer_requires_review" title="请先完成方舟客户档案和主负责人复核，再进行身份重绑。" type="warning" :closable="false" /><el-form-item label="已验证外部公司身份"><el-select v-model="form.identity_id" aria-label="已验证外部公司身份" placeholder="明确选择该客户公司身份"><el-option v-for="row in data.identities" :key="row.id" :label="`${row.company_id} · ${row.namespace}`" :value="row.id" /></el-select></el-form-item><p>只接受该方舟客户、配置来源下的已验证公司身份。不会把已有订单改为新外部公司，也不会替换既有 PI。</p></template>
          <el-form-item label="复核原因"><el-input v-model="form.reason" aria-label="复核原因" maxlength="500" type="textarea" :rows="2" /></el-form-item><el-checkbox v-model="confirmed">我已核对旧绑定、新对象、订单交接及历史读取范围，并确认客户需要重新启用</el-checkbox>
        </el-form>
      </template>
    </div>
    <template #footer><GlassButton :disabled="locked" @click="close">关闭</GlassButton><GlassButton :disabled="loading || state === 'sending'" @click="load(true)">读取当前复核并放弃草稿</GlassButton><GlassButton v-permission="'portal_access:admin'" :disabled="locked || !confirmed || !data" variant="primary" @click="save">确认本次复核</GlassButton></template>
  </el-dialog>
</template>

<style scoped>
.el-alert:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.el-alert { margin: 12px 0; } .el-form-item { margin-top: 20px; } .el-select { width: 100%; }
p { color: var(--text-secondary); line-height: 1.7; overflow-wrap: anywhere; } .el-pagination { padding: 16px 0; overflow-x: auto; }
.el-checkbox { height: auto; white-space: normal; } :deep(.el-checkbox__label) { white-space: normal; line-height: 1.6; }
.el-radio-group { display: flex; flex-wrap: wrap; }
:deep(.list-table .cell) { white-space: normal !important; overflow-wrap: anywhere; word-break: normal; }
</style>
<style>.portal-binding-review { max-width: calc(100vw - 24px); } .portal-binding-review .el-dialog__footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; } .portal-binding-review .el-dialog__footer button { margin-left: 0; }</style>
