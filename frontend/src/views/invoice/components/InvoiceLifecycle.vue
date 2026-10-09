<template>
  <DetailDrawer v-model="visible" title="订单取消与异常恢复" width="640px" append-to-body :close-on-click-modal="false">
    <div class="lifecycle-body" :aria-busy="busy">
      <p role="status">{{ promptVisible ? '请填写本次处理依据' : busy ? '正在读取或处理原任务，请稍候' : unknown ? '执行结果尚未确认，请先读取原任务' : '当前处理结果' }}</p>
      <template v-if="data">
        <h3>{{ data.invoice_no }}</h3>
        <el-alert :title="notice" type="info" :closable="false" />
        <p v-if="data.cancellation">本地处理状态：{{ states[data.cancellation.status] || data.cancellation.status }}</p>
        <p v-if="data.cancellation?.reason">取消原因：{{ data.cancellation.reason }}</p>
        <el-alert v-if="reviewRequired" title="远端结果待核对；本地终止不代表远端单据仍存在" type="warning" :closable="false" />
        <p v-if="data.recovery_summary">远端观测：{{ observations[data.recovery_summary.remote_observation] || '未知' }} · 待核对执行 {{ data.recovery_summary.pending_attempt_count }} 项<span v-if="data.recovery_summary.last_observed_at"> · {{ formatBeijingDateTime(data.recovery_summary.last_observed_at) }}</span></p>
        <section v-if="orderReviewRequired" aria-label="原订单推送核对">
          <el-alert title="原订单推送结果待核对，请勿再次创建订单" type="warning" :closable="false" />
          <p>原推送观测：{{ orderResults[data.order_push_summary.result_class] || '结果不明' }} · 待核对执行 {{ data.order_push_summary.pending_attempt_count }} 项<span v-if="data.order_push_summary.last_observed_at"> · {{ formatBeijingDateTime(data.order_push_summary.last_observed_at) }}</span></p>
          <p v-if="data.order_push_summary.original_order_id">原小满订单：{{ data.order_push_summary.original_order_id }}</p>
          <p>核对只读取原订单并验证金额与明细，不再次推送，也不自动恢复回款或出库。</p>
          <el-button v-if="orderResolution" v-permission="'invoice:admin'" :disabled="locked" type="primary" @click="act('order_review')">核对原推送订单</el-button>
          <p v-else>当前不能直接解除保护，请先核对原执行状态与处理依据。</p>
        </section>
        <p v-for="text in data.cancellation?.evidence?.blockers || []" :key="text">{{ text }}</p>
        <p v-for="doc in data.cancellation?.evidence?.outbounds || []" :key="doc.id">出库单 {{ doc.number || doc.id }}（{{ String(doc.status) === '2' ? '已出库' : '待核对' }}）</p>
        <p v-if="data.outbound">自动出库：{{ data.outbound.status }} · {{ data.outbound.reason || '等待处理' }}</p>
        <div class="lifecycle-actions">
          <el-button v-if="!data.cancellation || data.cancellation.status === 'aborted'" v-permission="'invoice:admin'" :disabled="locked" type="danger" @click="act('begin')">发起取消</el-button>
          <el-button v-if="terminal && reviewRequired" v-permission="'invoice:admin'" :disabled="locked" @click="act('refresh')">核对远端结果</el-button>
          <template v-if="data.cancellation && !terminal">
            <el-button v-permission="'invoice:admin'" :disabled="locked" @click="act('refresh')">核对关联单据</el-button>
            <el-button v-if="['pending','blocked'].includes(data.cancellation.status) && !reviewRequired" v-permission="'invoice:admin'" :disabled="locked" type="danger" @click="act('remove')">尝试删除小满订单</el-button>
            <el-button v-permission="'invoice:admin'" :disabled="locked" @click="act('retain')">终止本地业务并保留记录</el-button>
            <el-button v-if="['pending','blocked'].includes(data.cancellation.status) && !reviewRequired" v-permission="'invoice:admin'" :disabled="locked" @click="act('abort')">撤回取消申请</el-button>
          </template>
          <template v-if="!['cancel_pending','cancelled'].includes(data.status)">
            <el-button v-permission="'invoice:admin'" :disabled="locked" @click="act('outbound_retry')">恢复漏建 / 未发送出库</el-button>
            <el-button v-permission="'invoice:admin'" :disabled="locked" @click="act('ack_outbound')">确认出库资料已核对</el-button>
          </template>
        </div>
        <p>已有出库单不自动整单重建；退货、退款和库存冲销须按实际业务处理。核对不会重复删除或恢复客户发布。</p>
      </template>
      <div v-if="error" ref="feedback" role="alert" tabindex="-1"><el-alert :title="error" type="warning" :closable="false" /></div>
      <el-button ref="readButton" v-permission="'invoice:admin'" :disabled="busy" @click="load">读取原任务结果</el-button>
    </div>
  </DetailDrawer>
  <el-dialog v-model="promptVisible" title="确认处理" width="480px" class="invoice-lifecycle-prompt" append-to-body :close-on-click-modal="false" @closed="cancelPrompt" @opened="focusReason">
    <p>{{ prompts[prompt?.action] }}</p>
    <p v-if="prompt?.orderRecovery">原小满订单：{{ prompt.orderRecovery.original_order_id }}（{{ prompt.orderRecovery.resolution === 'bind_order' ? '核对后绑定原单' : '核对当前已绑定原单' }}）</p>
    <label for="invoice-lifecycle-reason">处理依据（10–500字）</label>
    <el-input id="invoice-lifecycle-reason" ref="reasonInput" v-model="promptReason" type="textarea" :rows="4" maxlength="500" show-word-limit />
    <p v-if="promptError" ref="promptFeedback" role="alert" tabindex="-1">{{ promptError }}</p>
    <template #footer><el-button @click="cancelPrompt">取消</el-button><el-button v-permission="'invoice:admin'" type="primary" @click="confirmPrompt">确认执行</el-button></template>
  </el-dialog>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { getInvoiceLifecycle, applyInvoiceLifecycle, resolveInvoiceSyncUncertain } from '@/api/invoice'
import { useAuthStore } from '@/stores/auth'
import { formatBeijingDateTime } from '@/utils/datetime'
const props = defineProps({ invoiceId: { type: Number, required: true } })
const emit = defineEmits(['changed'])
const auth = useAuthStore()
const visible = ref(false), data = ref(null), busy = ref(false), error = ref(''), unknown = ref(false), feedback = ref(null)
const promptVisible = ref(false), prompt = ref(null), promptReason = ref(''), promptError = ref(''), reasonInput = ref(null), promptFeedback = ref(null), readButton = ref(null)
let generation = 0, readSequence = 0
const terminal = computed(() => ['remote_deleted','retained','aborted'].includes(data.value?.cancellation?.status))
const reviewRequired = computed(() => data.value?.recovery_summary?.review_required === true)
const orderReviewRequired = computed(() => data.value?.order_push_summary?.review_required === true)
const orderResolution = computed(() => ['bind_order', 'confirm_existing'].includes(data.value?.order_push_summary?.resolution) ? data.value.order_push_summary.resolution : null)
const orderResults = { accepted: '已受理，需核对原单', rejected: '明确拒绝，原任务仍待核对', unknown: '结果不明', conflicting: '原单身份存在冲突', not_observed: '尚无结果观测' }
const locked = computed(() => busy.value || unknown.value)
const states = { pending: '待核对', blocked: '有关联事项待处理', deleting: '删除处理中', uncertain: '删除结果待核对', remote_deleted: '远端已删除，本地归档', retained: '本地业务已终止，记录已保留', aborted: '取消已撤回' }
const observations = { absent: '不存在', present: '存在', unknown: '未知', not_checked: '尚未观测' }
const notice = computed(() => data.value?.cancellation?.status === 'retained' ? '本地处理已终止，原记录保留；远端结果以核对证据为准。' : data.value?.cancellation?.message || '取消前将冻结订单编辑、新回款发送和自动出库，保留已发生的货款记录。')
const prompts = {
  order_review: '系统将读取已记录的原小满订单，核对客户、币种、金额和全部明细；请填写核对依据。不会再次创建订单或自动完成库存、回款及出库。',
  begin: '将冻结订单编辑、新回款发送和自动出库。请填写取消原因。',
  remove: '将实时核对并尝试删除小满订单，方舟保留原单。请确认已处理关联货款并填写依据。',
  retain: '终止本地后续业务并保留方舟记录。已外发的远端结果仍需核对，不执行退款或库存冲销；请填写处理安排。',
  abort: '仅撤回尚未外发的取消申请；不自动恢复客户PI发布。请填写撤回原因。',
  outbound_retry: '仅恢复未发送或漏建任务。已有出库、结果不确定及删除后任务不会重建。请填写核对依据。',
  ack_outbound: '系统会重新核对数量与明细关联；请确认价格、地址、备注已经人工核对，填写依据。',
}
function reset() { ++generation; ++readSequence; data.value = null; busy.value = false; error.value = ''; unknown.value = false; promptVisible.value = false; prompt.value = null; promptReason.value = ''; promptError.value = '' }
function identity() { return JSON.stringify([auth.user?.id, auth.user?.roles, auth.user?.permissions]) }
function context() { return { generation, invoiceId: props.invoiceId, actor: identity() } }
function current(ctx) { return visible.value && ctx.generation === generation && ctx.invoiceId === props.invoiceId && ctx.actor === identity() }
async function showError(message, ctx) {
  if (!current(ctx)) return
  error.value = message
  await nextTick()
  if (current(ctx)) feedback.value?.focus()
}
function denied(errorValue) { return [401,403,404].includes(errorValue.response?.status) }
async function load() {
  const ctx = context(), sequence = ++readSequence
  busy.value = true
  try {
    const result = await getInvoiceLifecycle(ctx.invoiceId)
    if (!current(ctx) || sequence !== readSequence) return false
    if (Number(result?.invoice_id) !== ctx.invoiceId) throw new Error('Invalid invoice response')
    data.value = result; error.value = ''; unknown.value = false
    return true
  } catch (failure) {
    if (!current(ctx) || sequence !== readSequence) return false
    if (denied(failure)) data.value = null
    unknown.value = true
    await showError(denied(failure) ? '当前账号无法读取此原任务；此前操作是否执行仍需有权人员核对。' : '原任务结果暂不可用，请稍后读取；不要重复发送。', ctx)
    return false
  } finally { if (current(ctx) && sequence === readSequence) busy.value = false }
}
async function open() { reset(); visible.value = true; await load() }
defineExpose({ open })
watch(() => [props.invoiceId, identity()], () => { visible.value = false; reset() })
watch(visible, value => { if (!value) reset() })
onBeforeUnmount(reset)
function focusReason() { if (promptVisible.value && prompt.value && current(prompt.value.ctx)) reasonInput.value?.focus() }
function cancelPrompt() {
  if (!prompt.value) return
  const { ctx, origin } = prompt.value
  prompt.value = null; promptVisible.value = false; promptReason.value = ''; promptError.value = ''
  if (current(ctx)) { busy.value = false; restoreFocus(ctx, origin) }
}
async function restoreFocus(ctx, origin) {
  await nextTick()
  if (!current(ctx)) return
  if (error.value) feedback.value?.focus()
  else if (origin?.isConnected && !origin.disabled) origin.focus()
  else readButton.value?.$el?.focus()
}
async function confirmPrompt() {
  const captured = prompt.value
  if (!captured || !current(captured.ctx)) { cancelPrompt(); return }
  const reason = promptReason.value.trim()
  if (reason.length < 10 || reason.length > 500) {
    promptError.value = '请填写10–500字的处理依据'
    await nextTick()
    if (prompt.value === captured && current(captured.ctx)) promptFeedback.value?.focus()
    return
  }
  prompt.value = null; promptVisible.value = false; promptReason.value = ''; promptError.value = ''
  await sendAction(captured.action, reason, captured.ctx, captured.version, captured.orderRecovery)
  await restoreFocus(captured.ctx, captured.origin)
}
async function act(action) {
  if (locked.value || !data.value) return
  const ctx = context(), version = data.value.version
  if (action === 'order_review' && !orderResolution.value) return
  const orderRecovery = action === 'order_review' ? { resolution: orderResolution.value, original_order_id: data.value.order_push_summary.original_order_id } : null
  busy.value = true
  if (action !== 'refresh') {
    prompt.value = { action, ctx, version, orderRecovery, origin: document.activeElement }; promptReason.value = ''; promptError.value = ''; promptVisible.value = true
    return
  }
  await sendAction(action, '管理员请求重新核对原订单及关联单据', ctx, version)
}
async function sendAction(action, reason, ctx, version, orderRecovery = null) {
  if (!current(ctx)) return
  error.value = ''; unknown.value = true
  try {
    if (action === 'order_review') {
      await resolveInvoiceSyncUncertain(ctx.invoiceId, { resolution: orderRecovery.resolution, reason, xiaoman_order_id: orderRecovery.resolution === 'bind_order' ? orderRecovery.original_order_id : null })
    } else {
      await applyInvoiceLifecycle(ctx.invoiceId, { action, reason, expected_version: version, confirmed: true })
    }
    if (!current(ctx)) return
    if (await load()) emit('changed')
  } catch (failure) {
    if (!current(ctx)) return
    if (denied(failure)) {
      data.value = null
      await showError('当前权限已变化，无法确认原操作结果；请由有权人员核对。', ctx)
    } else {
      await showError('执行结果尚未确认，请读取原任务；不要重复发送。', ctx)
      await load()
      if (action === 'order_review' && current(ctx)) await showError('本次核对未确认，请查看原任务最新状态后再处理。', ctx)
    }
  } finally { if (current(ctx)) busy.value = false }
}
</script>
<style scoped>
.lifecycle-body { padding: 0 12px; }
.lifecycle-actions { display: flex; gap: 12px; flex-wrap: wrap; margin: 20px 0; }
p { color: var(--text-secondary); line-height: 1.7; overflow-wrap: anywhere; }
</style>
<style>
.invoice-lifecycle-prompt { max-width: 94vw; }
</style>
