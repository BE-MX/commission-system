<template>
  <section v-if="['stock', 'presale'].includes(form.order_type)" class="receipt-card">
    <div class="card-title">{{ form.order_type === 'presale' ? '首笔定金' : '本次回款' }} <el-tag effect="plain" type="warning" size="small">同步前必填</el-tag></div>
    <p class="receipt-hint">{{ form.receipt_draft?.status === 'converted' ? '本次回款已生成，订单重新同步不会重复建款。' : '上传实际到账截图；订单完整同步后自动生成回款单。回款金额默认随预付款填入，可手改；可先保存草稿。' }}</p>
    <!-- 小满回款方式在其接口中非必填，且口径与内部付款方式不同；自动回款单统一按 Other 提交 -->
    <p class="method-note">小满回款方式默认按 Other 提交（小满侧非必填），无需选择。</p>
    <p v-if="form.order_type === 'presale'">请填写实际定金金额；定金保留至最后一批出库抵扣。</p>
    <ReceiptFields v-if="form.receipt_draft" :form="form.receipt_draft" :currency="form.currency"
      :readonly="frozen" hide-payment-type @uploading="v => form.receipt_uploading = v" />
    <p v-if="form.receipt_draft?.last_error" class="receipt-error" role="alert">{{ form.receipt_draft.last_error }}</p>
    <p v-if="form.receipt_draft?.eligible === false" class="receipt-hint">此单为历史库存单，补传凭证后可同步订单，已有回款不会自动补建。</p>
  </section>
</template>
<script setup>
import { computed, watch } from 'vue'
import ReceiptFields from '@/views/receipt/ReceiptFields.vue'
import { currentBeijingDate } from '@/utils/datetime'
const props = defineProps({ form: { type: Object, required: true } })
const frozen = computed(() => props.form.receipt_draft?.status && props.form.receipt_draft.status !== 'draft')
watch(() => props.form.receipt_draft, value => {
  if (!value) props.form.receipt_draft = { amount: props.form.order_type === 'presale' ? null : props.form.internal_received > 0 ? props.form.internal_received : null,
    collection_date: currentBeijingDate(), payment_type: 'Other',
    attachment_ids: [], remark: '', status: 'draft' }
}, { immediate: true })
// 回款金额随预付款自动填入（2026-09-23）：只跟随未被手改过的草稿金额
watch(() => props.form.internal_received, (value, previous) => {
  const draft = props.form.receipt_draft
  if (props.form.order_type !== 'presale' && !frozen.value && !props.form.id && draft && (draft.amount == null || draft.amount === previous)) {
    draft.amount = value > 0 ? value : null
  }
})
</script>
<style scoped>
.receipt-card { display: block; }
.card-title { display: flex; align-items: center; gap: 8px; margin: 0 0 10px; font-size: 14px; font-weight: 700; color: var(--text-primary); }
.receipt-hint { margin: 0 0 10px; font-size: 12px; color: var(--text-secondary); line-height: 1.6; }
.method-note { margin: 0 0 12px; font-size: 12px; color: var(--text-muted); line-height: 1.6; padding: 6px 10px; border-radius: 8px; background: var(--table-header-bg); }
.receipt-error { margin: 8px 0 0; font-size: 12px; color: var(--color-danger); line-height: 1.6; }
</style>
