<template>
  <span class="receipt-delete-action">
    <GlassButton v-if="eligible" v-permission="'receipt:delete'" :variant="receipt.deletion_pending ? 'secondary' : 'danger'"
      left-icon="Delete" :disabled="disabled || busy" @click="open">
      {{ receipt.deletion_pending ? '继续核验删除' : '删除回款单' }}
    </GlassButton>
    <el-dialog v-model="visible" title="删除回款单" width="640px" class="receipt-delete-dialog" append-to-body
      :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" :before-close="close">
      <el-alert title="只删除这笔回款单，保留订单、凭证和审计记录；此操作不执行退款。核验删除后才能重新登记回款。"
        type="warning" :closable="false" show-icon />
      <div v-loading="busy" class="receipt-delete-content" aria-live="polite">
        <template v-if="proof">
          <el-descriptions :column="1" border>
            <el-descriptions-item label="订单发票">{{ proof.invoice_no }}</el-descriptions-item>
            <el-descriptions-item label="回款单号">{{ proof.receipt_no }}</el-descriptions-item>
            <el-descriptions-item label="回款金额（含费）">{{ proof.currency }} {{ formatMoney(proof.amount) }}</el-descriptions-item>
            <el-descriptions-item label="手续费">{{ proof.currency }} {{ formatMoney(proof.bank_charge) }}</el-descriptions-item>
            <el-descriptions-item label="实际到账净额">{{ proof.currency }} {{ formatMoney(proof.net_amount) }}</el-descriptions-item>
          </el-descriptions>
          <p v-if="proof.can_resume" class="receipt-delete-note">原删除请求已记录。继续核验只查询原单，不会再次发送删除。</p>
          <p v-else-if="proof.remote_state === 'local'" class="receipt-delete-note">这笔回款尚未在小满创建，将在方舟作废并保留原记录。</p>
          <p v-else-if="proof.remote_state === 'deleted'" class="receipt-delete-note">小满原回款已删除；确认后归档方舟原记录。</p>
          <el-form label-position="top">
            <el-form-item label="删除原因" :required="proof.can_delete">
              <el-input v-model="reason" type="textarea" :rows="2" maxlength="500" show-word-limit
                :disabled="busy || proof.can_resume" placeholder="例如：回款资料录入错误，用户重新提交" aria-label="删除原因" />
            </el-form-item>
          </el-form>
          <el-checkbox v-if="proof.can_delete" v-model="confirmed" :disabled="busy">确认只删除以上回款单，保留原凭证与审计</el-checkbox>
        </template>
        <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      </div>
      <template #footer>
        <div class="dialog-footer receipt-delete-footer">
          <GlassButton :disabled="busy" @click="close()">关闭</GlassButton>
          <GlassButton :disabled="busy || disabled" left-icon="Refresh" @click="load">重新读取原单</GlassButton>
          <GlassButton v-permission="'receipt:delete'" :variant="proof?.can_resume ? 'primary' : 'danger'" :loading="busy"
            :disabled="disabled || !canSubmit" @click="submit">{{ proof?.can_resume ? '继续核验' : '确认删除' }}</GlassButton>
        </div>
      </template>
    </el-dialog>
  </span>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { getAuthEpoch, useAuthStore } from '@/stores/auth'
import { deleteReceipt, previewReceiptDeletion } from '@/api/receipt'
import { formatMoney } from '@/utils/money'
import { msgSuccessText, msgWarning } from '@/utils/feedback'

const props = defineProps({ receipt: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['updated', 'busy', 'open'])
const auth = useAuthStore()
const allowed = computed(() => auth.hasPermission('receipt:delete'))
const eligible = computed(() => props.receipt.status === 'active' && !props.receipt.batch_id
  && (props.receipt.purpose || 'ordinary') === 'ordinary')
const visible = ref(false), busy = ref(false), proof = ref(null), error = ref(''), reason = ref(''), confirmed = ref(false)
const canSubmit = computed(() => Boolean(proof.value?.can_resume
  || proof.value?.can_delete && confirmed.value && reason.value.trim().length >= 2))
let generation = 0, controller = null, disposed = false

function context() {
  controller?.abort(); controller = new AbortController()
  return { id: props.receipt.id, epoch: getAuthEpoch(), generation: ++generation, signal: controller.signal }
}
function current(ctx) {
  return !disposed && visible.value && allowed.value && ctx.generation === generation
    && ctx.id === props.receipt.id && ctx.epoch === getAuthEpoch()
}
function reset() {
  ++generation; controller?.abort(); proof.value = null; error.value = ''; confirmed.value = false
  reason.value = ''; busy.value = false; visible.value = false
}
function close(done) {
  if (busy.value) return
  reset()
  if (typeof done === 'function') done()
}
async function load() {
  if (busy.value || props.disabled || !allowed.value || !visible.value) return
  const ctx = context()
  busy.value = true; proof.value = null; confirmed.value = false; error.value = ''
  try {
    const result = await previewReceiptDeletion(ctx.id, ctx.signal)
    if (!current(ctx)) return
    proof.value = result
    if (result.can_resume) reason.value = result.reason
    if (!result.can_delete && !result.can_resume) {
      closeAfterResult(); emit('updated', result.receipt)
    }
  } catch (e) {
    if (current(ctx)) error.value = e.response?.data?.detail || '删除范围尚未核验，请重新读取原单'
  } finally { if (ctx.generation === generation && !disposed) busy.value = false }
}
function closeAfterResult() { busy.value = false; visible.value = false; proof.value = null }
async function open() {
  if (props.disabled || busy.value || !allowed.value || !eligible.value) return
  reset(); visible.value = true; await load()
}
async function submit() {
  if (props.disabled || busy.value || !allowed.value || !canSubmit.value) return
  const ctx = context(), captured = proof.value
  busy.value = true; error.value = ''
  try {
    const result = await deleteReceipt(ctx.id, { expected_version: captured.expected_version,
      confirmed: true, reason: reason.value.trim() }, ctx.signal)
    if (!current(ctx)) return
    proof.value = null; confirmed.value = false; busy.value = false
    if (result.status === 'deleted') {
      visible.value = false; msgSuccessText(result.message); emit('updated', result.receipt)
    } else {
      visible.value = false; msgWarning(result.message); emit('updated', result.receipt)
    }
  } catch (e) {
    if (current(ctx)) {
      proof.value = null; confirmed.value = false
      error.value = e.response?.data?.detail || '删除结果尚未确认，请重新读取原单继续核验；不要重新创建回款'
    }
  } finally { if (ctx.generation === generation && !disposed) busy.value = false }
}
watch(() => [props.receipt.id, allowed.value, auth.user?.id, auth.user?.sub, auth.accessToken, getAuthEpoch()], reset)
watch(busy, value => emit('busy', value), { flush: 'sync' })
watch(visible, value => emit('open', value), { flush: 'sync' })
onBeforeUnmount(() => { disposed = true; reset(); emit('busy', false); emit('open', false) })
</script>

<style scoped>
.receipt-delete-action { display: inline-flex; }
:global(.receipt-delete-dialog) { max-width: calc(100vw - 24px); }
.receipt-delete-content { margin-top: 16px; display: grid; gap: 16px; }
.receipt-delete-note { margin: 0; color: var(--text-secondary); }
.receipt-delete-footer { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }
</style>
