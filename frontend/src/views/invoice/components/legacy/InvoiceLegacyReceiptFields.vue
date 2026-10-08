<template>
  <section v-if="form.order_type === 'stock'" class="head-section receipt-section">
    <div class="col-title">本次回款 <StatusBadge effect="plain" type="warning">同步前必填</StatusBadge></div>
    <p>{{ form.receipt_draft?.status === 'converted' ? '本次回款已生成，订单重新同步不会重复建款。' : '上传实际到账截图；订单完整同步后自动生成回款单。可先保存草稿。' }}</p>
    <ReceiptFields v-if="form.receipt_draft" :form="form.receipt_draft" :currency="form.currency"
      :readonly="frozen" :hide-proofs="canEditProofs" @uploading="v => form.receipt_uploading = v" />
    <InvoiceConvertedProofs v-if="canEditProofs" :key="`${form.receipt_draft.receipt_id}:${form.receipt_draft.receipt_version}`" :receipt-id="form.receipt_draft.receipt_id"
      :locked="form.receipt_action_open || form.receipt_action_busy"
      @saved="(id, ids) => { if (form.receipt_draft?.receipt_id === id) form.receipt_draft.attachment_ids = ids }"
      @uploading="value => form.receipt_uploading = value"
      @dirty="value => form.receipt_proof_dirty = value" />
    <p v-if="form.receipt_draft?.last_error" role="alert">{{ form.receipt_draft.last_error }}</p>
    <p v-if="form.receipt_draft?.eligible === false">此单为历史库存单，补传凭证后可同步订单，已有回款不会自动补建。</p>
    <InvoiceReceiptActions v-if="form.id" :form="form" :total="total" />
  </section>
</template>
<script setup>
import { computed, watch } from 'vue'
import ReceiptFields from '@/views/receipt/ReceiptFields.vue'
import InvoiceConvertedProofs from '../InvoiceConvertedProofs.vue'
import InvoiceReceiptActions from '../InvoiceReceiptActions.vue'
import { nextDraftAmount } from '../../composables/invoiceReceiptState'
import { useAuthStore } from '@/stores/auth'
import { currentBeijingDate } from '@/utils/datetime'

// 旧版下单抽屉的回款区（HEAD 版原样保留，过渡期使用）：回款方式独立下拉小满回款方式
const props = defineProps({ form: { type: Object, required: true }, total: Number })
const frozen = computed(() => props.form.receipt_draft?.status && props.form.receipt_draft.status !== 'draft')
const auth = useAuthStore()
const canEditProofs = computed(() => props.form.receipt_draft?.status === 'converted' &&
  props.form.receipt_draft?.receipt_status === 'active' && props.form.receipt_draft?.receipt_id && auth.hasPermission('receipt:write'))
watch(() => props.form.receipt_draft, value => {
  if (!value) props.form.receipt_draft = { amount: props.form.order_type === 'presale' ? null : props.form.internal_received > 0 ? Number(props.form.internal_received) : null,
    collection_date: currentBeijingDate(), payment_type: '', attachment_ids: [], remark: '', status: 'draft' }
}, { immediate: true })
watch(() => [props.form.id, props.form.internal_received], ([id, value], [previousId, previous]) => {
  const draft = props.form.receipt_draft
  if (id === previousId && draft) draft.amount = nextDraftAmount(draft, previous, value, props.form.order_type)
})
</script>
<style scoped>
.receipt-section p{font-size:12px;color:var(--text-secondary);line-height:1.8}.receipt-section{border-top:1px solid var(--border-color);padding-top:16px}
.head-section { max-width: 1400px; padding-bottom: 2px; margin: 18px 0 10px; border-bottom: 1px solid var(--border-color); }
.col-title { margin: 2px 0 10px; color: var(--text-secondary); font-size: 14px; font-weight: 700; }
</style>
