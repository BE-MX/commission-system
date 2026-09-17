<template>
  <section v-if="form.order_type === 'stock'" class="head-section receipt-section">
    <div class="col-title">本次回款 <el-tag effect="plain" type="warning">同步前必填</el-tag></div>
    <p>{{ form.receipt_draft?.status === 'converted' ? '本次回款已生成，订单重新同步不会重复建款。' : '上传实际到账截图；订单完整同步后自动生成回款单。可先保存草稿。' }}</p>
    <ReceiptFields v-if="form.receipt_draft" :form="form.receipt_draft" :currency="form.currency"
      :readonly="frozen" @uploading="v => form.receipt_uploading = v" />
    <p v-if="form.receipt_draft?.last_error" role="alert">{{ form.receipt_draft.last_error }}</p>
    <p v-if="form.receipt_draft?.eligible === false">此单为历史库存单，补传凭证后可同步订单，已有回款不会自动补建。</p>
  </section>
</template>
<script setup>
import { computed, watch } from 'vue'
import ReceiptFields from '@/views/receipt/ReceiptFields.vue'
import { currentBeijingDate } from '@/utils/datetime'
const props = defineProps({ form: { type: Object, required: true }, total: Number })
const frozen = computed(() => props.form.receipt_draft?.status && props.form.receipt_draft.status !== 'draft')
watch(() => props.form.receipt_draft, value => {
  if (!value) props.form.receipt_draft = { amount: props.total > 0 ? props.total : null,
    collection_date: currentBeijingDate(), payment_type: '', attachment_ids: [], remark: '', status: 'draft' }
}, { immediate: true })
watch(() => props.total, (value, previous) => {
  const draft = props.form.receipt_draft
  if (!frozen.value && !props.form.id && draft && (draft.amount == null || draft.amount === previous)) {
    draft.amount = value > 0 ? value : null
  }
})
</script>
<style scoped>
.receipt-section p{font-size:12px;color:var(--text-secondary);line-height:1.8}.receipt-section{border-top:1px solid var(--border-color);padding-top:16px}
</style>
