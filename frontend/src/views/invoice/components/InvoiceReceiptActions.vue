<template>
  <section v-if="canRead" class="invoice-funds" v-loading="loading">
    <div class="funds-title">实际回款与待收 <StatusBadge v-if="receipt" size="small" effect="plain">{{ action.label }}</StatusBadge></div>
    <p class="funds-note">预付款与尾款是订单结算信息；实际回款按回款单核验。修改明细不会改写原收款。</p>
    <template v-if="summary">
      <dl v-if="form.order_type === 'presale' && summary.balance" class="funds-grid">
        <div><dt>已生效留存余额（含定金及费用）</dt><dd>{{ form.currency }} {{ formatMoney(summary.balance.pool_available_amount) }}</dd></div>
        <div v-for="pool in summary.balance.pool_balances || []" :key="pool.receipt_id"><dt>{{ purposeLabel(pool.purpose) }}{{ pool.effective ? '余额' : '（待生效）' }}</dt><dd>{{ formatMoney(pool.remaining_amount) }}</dd></div>
        <div><dt>待处理收款</dt><dd>{{ formatMoney(summary.balance.pending_amount) }}</dd></div>
      </dl>
      <dl v-else-if="summary.balance" class="funds-grid">
        <div><dt>{{ form.receipt_order_dirty ? '编辑后应收（预览）' : '订单应收' }}</dt><dd>{{ form.currency }} {{ formatMoney(total) }}</dd></div>
        <div><dt>已生效回款（含费）</dt><dd>{{ formatMoney(summary.balance.effective_amount) }}</dd></div>
        <div><dt>待处理回款</dt><dd>{{ formatMoney(summary.balance.pending_amount) }}</dd></div>
        <div><dt>{{ projected.overpaid > 0 ? '已生效超收' : '待收金额' }}</dt><dd>{{ formatMoney(projected.overpaid || projected.unpaid) }}</dd></div>
      </dl>
      <p v-if="form.order_type !== 'presale' && projected?.overpaid > 0" class="funds-warning">已生效回款超过当前应收，请核实退款安排；原回款保留。</p>
      <p v-if="form.order_type !== 'presale' && projected?.pendingExcess > 0" class="funds-warning">另有待处理金额超出应收 {{ formatMoney(projected.pendingExcess) }}，请核对原回款；这部分不表示已实际超收。</p>
      <p v-if="receipt" class="funds-note">原回款：{{ formatMoney(receipt.amount) }} {{ receipt.currency }} · {{ action.hint }}</p>
      <p v-if="blockedReason" class="funds-warning" role="status">{{ blockedReason }}</p>
      <p v-if="form.order_type === 'presale'" class="funds-note">预售定金与分批回款请在发货结算或整笔回款中处理。</p>
      <div class="funds-actions">
        <GlassButton v-if="action.editable" v-permission="'receipt:write'" left-icon="Edit" :disabled="writeBlocked" @click="mode = 'edit'">修正回款</GlassButton>
        <GlassButton v-if="receipt?.sync_status === 'failed' && action.editable" v-permission="'receipt:write'" left-icon="Refresh" :disabled="writeBlocked" :loading="busy" @click="retry">重试同步</GlassButton>
        <GlassButton v-permission="'receipt:write'" left-icon="Plus" :disabled="writeBlocked || (form.order_type !== 'presale' && Number(summary.balance?.remaining_amount) <= 0)" @click="mode = 'create'">{{ form.order_type === 'presale' ? '登记预售收款' : '补登记回款' }}</GlassButton>
        <ReceiptPurposeCorrection v-if="form.order_type === 'presale' && receipt" :receipt="receipt" :disabled="writeBlocked" @updated="updated" @busy="value => remoteBusy = value" @open="value => remoteOpen = value" />
        <ReceiptRemoteChange v-if="receipt?.status === 'active' && receipt.xiaoman_receipt_id && !receipt.batch_id && receipt.purpose !== 'presale_deposit'"
          :receipt-id="receipt.id" :disabled="localBlocked" @busy="value => remoteBusy = value" @open="value => remoteOpen = value" @updated="updated" />
      </div>
    </template>
    <p v-if="error" class="funds-error" role="alert">{{ error }}</p>
    <div class="funds-actions">
      <GlassButton left-icon="Refresh" :disabled="busy || remoteBusy || Boolean(mode) || form.receipt_uploading || form.receipt_proof_dirty || form.receipt_remark_editing || form.receipt_remark_saving" @click="load">刷新资金汇总</GlassButton>
      <a :href="managementUrl" target="_blank" rel="noopener" class="funds-link">查看 / 核对回款单</a>
    </div>
    <InvoiceReceiptPaymentDialog v-if="mode" :key="`${form.id}:${mode}`" :invoice="form" :receipt="mode === 'edit' ? receipt : undefined"
      :balance="summary.balance" :blocked="writeBlocked" @busy="value => dialogBusy = value" @close="mode = null" @saved="updated" />
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { getInvoiceReceiptSummary, retryReceipt } from '@/api/receipt'
import { formatMoney } from '@/utils/money'
import GlassButton from '@/components/GlassButton.vue'
import ReceiptRemoteChange from '@/views/receipt/ReceiptRemoteChange.vue'
import ReceiptPurposeCorrection from '@/views/receipt/ReceiptPurposeCorrection.vue'
import { purposeLabel } from './invoiceDetailLabels'
import InvoiceReceiptPaymentDialog from './InvoiceReceiptPaymentDialog.vue'
import { applySubmittedReceipt, projectReceiptBalance, receiptActionState } from '../composables/invoiceReceiptState'

const props = defineProps({ form: { type: Object, required: true }, total: { type: Number, required: true } })
const auth = useAuthStore()
const canRead = computed(() => auth.hasAnyPermission(['receipt:read', 'receipt:write', 'receipt:admin']))
const loading = ref(false), busy = ref(false), dialogBusy = ref(false), remoteBusy = ref(false)
const remoteOpen = ref(false)
const summary = ref(null), mode = ref(null), error = ref('')
const receipt = computed(() => summary.value?.initial_receipt)
const action = computed(() => receiptActionState(receipt.value))
const projected = computed(() => summary.value?.balance ? projectReceiptBalance(summary.value.balance, props.total) : null)
const blockedReason = computed(() => props.form.receipt_order_dirty
  ? props.form.presale_edit_blocked_reason
    ? '主单有未保存修改，当前批次未完成，暂不能保存。请关闭并重新打开订单，恢复已保存内容后，再按页脚指引处理回款。'
    : '订单有未保存修改，请先保存并完成关联同步，再处理回款。'
  : summary.value?.action_blocked_reason)
const localBlocked = computed(() => loading.value || busy.value || dialogBusy.value || Boolean(props.form.receipt_order_dirty || props.form.receipt_uploading || props.form.receipt_proof_dirty || props.form.receipt_remark_editing || props.form.receipt_remark_saving))
const writeBlocked = computed(() => localBlocked.value || remoteBusy.value || Boolean(blockedReason.value) || !summary.value?.balance)
const managementUrl = computed(() => props.form.xiaoman_order_id
  ? `/invoice/receipts?order_id=${encodeURIComponent(props.form.xiaoman_order_id)}`
  : `/invoice/receipts?keyword=${encodeURIComponent(props.form.invoice_no || '')}`)
let sequence = 0, disposed = false

function applyReceipt(row) {
  applySubmittedReceipt(props.form, row)
}

async function load() {
  if (!props.form.id || !canRead.value || busy.value || remoteBusy.value || mode.value || props.form.receipt_uploading || props.form.receipt_proof_dirty || props.form.receipt_remark_editing || props.form.receipt_remark_saving) return
  const current = ++sequence, id = props.form.id
  loading.value = true; summary.value = null; error.value = ''
  try {
    const data = await getInvoiceReceiptSummary(id)
    if (disposed || current !== sequence || props.form.id !== id) return
    summary.value = data
    if (data.initial_receipt) applyReceipt(data.initial_receipt)
  } catch (e) {
    if (!disposed && current === sequence) error.value = e.response?.data?.detail || '资金汇总未核验，请刷新或打开回款单处理'
  } finally { if (!disposed && current === sequence) loading.value = false }
}

async function updated(row) {
  if (disposed || row.invoice_id !== props.form.id) return
  applyReceipt(row); mode.value = null
  await nextTick(); await load()
}
async function retry() {
  if (writeBlocked.value || !action.value.editable || receipt.value?.sync_status !== 'failed') return
  const id = props.form.id
  busy.value = true; error.value = ''
  try {
    const row = await retryReceipt(receipt.value.id)
    if (!disposed && props.form.id === id) applyReceipt(row)
  } catch (e) { if (!disposed && props.form.id === id) error.value = e.response?.data?.detail || '重试结果未确认，请核对原回款' }
  finally { busy.value = false }
  if (!disposed && props.form.id === id && !error.value) await load()
}
watch(() => [props.form.id, props.form.sync_status, props.form.linked_sync_id, canRead.value], () => {
  sequence += 1; summary.value = null; mode.value = null; load()
}, { immediate: true })
watch(() => Boolean(mode.value || remoteOpen.value), value => { props.form.receipt_action_open = value })
watch(() => busy.value || dialogBusy.value || remoteBusy.value, value => { props.form.receipt_action_busy = value })
onBeforeUnmount(() => { disposed = true; sequence += 1; props.form.receipt_action_open = false; props.form.receipt_action_busy = false })
</script>

<style scoped>
.invoice-funds { margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--border-color); }
.funds-title { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; font-size: 14px; font-weight: 700; }
.funds-note, .funds-warning, .funds-error { font-size: 12px; line-height: 1.6; margin: 8px 0; }
.funds-note { color: var(--text-secondary); }
.funds-warning { color: var(--color-warning-text); }
.funds-error { color: var(--color-danger-text); }
.funds-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin: 12px 0; }
.funds-grid dt { font-size: 12px; color: var(--text-secondary); }
.funds-grid dd { margin: 4px 0 0; font-weight: 600; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
.funds-actions { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-top: 10px; }
.funds-link { font-size: 12px; color: var(--color-primary); }
@media (max-width: 480px) { .funds-grid { grid-template-columns: 1fr; } }
</style>
