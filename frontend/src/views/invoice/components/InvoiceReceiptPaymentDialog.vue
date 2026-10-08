<template>
  <el-dialog :model-value="true" :title="receipt ? '修正原回款' : '补登记实际回款'" width="640px" append-to-body
    :close-on-click-modal="false" :before-close="close">
    <el-form label-position="top">
      <p>{{ invoice.invoice_no }} · {{ invoice.currency }}；此操作独立保存，不修改订单明细。</p>
      <p v-if="receipt?.source === 'auto'">自动回款的手续费按最新订单重新分摊，保存后在原单重试同步。</p>
      <p v-if="!receipt">本次可登记 {{ formatMoney(balance.remaining_amount) }}；请填写本次实际收到的金额。</p>
      <ReceiptFields :form="payment" :currency="invoice.currency" :readonly="saving" :show-charge="receipt?.source !== 'auto'"
        :hide-payment-type="receipt?.source === 'auto'" @uploading="value => uploading = value" />
      <el-alert v-if="error" :title="error" type="error" :closable="false" />
    </el-form>
    <template #footer>
      <GlassButton :disabled="saving || uploading" @click="close()">取消</GlassButton>
      <GlassButton v-permission="'receipt:write'" variant="primary" :loading="saving" :disabled="uploading || blocked" @click="submit">
        {{ receipt ? '保存修正' : '登记回款' }}
      </GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import ReceiptFields from '@/views/receipt/ReceiptFields.vue'
import { createReceipt, updateReceipt } from '@/api/receipt'
import { currentBeijingDate } from '@/utils/datetime'
import { formatMoney } from '@/utils/money'
import { confirmAction, msgSuccessText } from '@/utils/feedback'
import { cents } from '@/views/receipt/batchReceiptState'

const props = defineProps({ invoice: { type: Object, required: true }, receipt: Object,
  balance: { type: Object, required: true }, blocked: Boolean })
const emit = defineEmits(['close', 'saved', 'busy'])
const saving = ref(false), uploading = ref(false), error = ref('')
const payment = reactive({ amount: props.receipt ? Number(props.receipt.amount) : null,
  bank_charge: Number(props.receipt?.bank_charge || 0),
  collection_date: props.receipt?.collection_date || currentBeijingDate(),
  payment_type: props.receipt?.payment_type || '', remark: props.receipt?.remark || '',
  attachment_ids: props.receipt?.attachments?.map(file => file.id) || [] })
const initial = JSON.stringify(payment), requestKey = crypto.randomUUID()
let disposed = false
watch(() => saving.value || uploading.value, value => emit('busy', value))

async function close(done) {
  if (saving.value || uploading.value) return
  if (JSON.stringify(payment) !== initial) {
    try { await confirmAction('尚未提交的回款信息将被丢弃，确定关闭？', '关闭回款操作', { type: 'warning' }) } catch { return }
  }
  emit('close'); if (typeof done === 'function') done()
}

async function submit() {
  if (saving.value || uploading.value || props.blocked) return
  const amount = cents(payment.amount), charge = cents(payment.bank_charge)
  if (amount == null || amount <= 0 || charge == null || charge < 0 ||
      (props.receipt?.source !== 'auto' && charge > amount) || !payment.collection_date || !payment.payment_type || !payment.attachment_ids.length) {
    error.value = '请核对金额、手续费、日期、方式，并至少保留一张凭证'; return
  }
  if (!props.receipt && amount > cents(props.balance.remaining_amount)) { error.value = '金额超过可登记余额，请关闭窗口并刷新资金汇总'; return }
  saving.value = true; error.value = ''
  const id = props.invoice.id
  try {
    const fields = { ...payment, amount: String(payment.amount), bank_charge: props.receipt?.source === 'auto' ? '0' : String(payment.bank_charge || 0), attachment_ids: [...payment.attachment_ids] }
    const row = props.receipt ? await updateReceipt(props.receipt.id, { ...fields, version: props.receipt.version })
      : await createReceipt({ ...fields, invoice_id: id, balance_version: props.balance.version, request_key: requestKey })
    if (disposed || props.invoice.id !== id) return
    msgSuccessText(props.receipt ? '回款已修正，请在原单重试同步' : '回款已登记，等待同步小满')
    emit('saved', row)
  } catch (e) {
    if (!disposed) error.value = e.response?.data?.detail || e.message || '保存结果未确认，资料已保留，请勿另建回款'
  } finally { saving.value = false }
}
onBeforeUnmount(() => { disposed = true; emit('busy', false) })
</script>
