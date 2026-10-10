<template>
  <section v-if="['stock', 'presale'].includes(form.order_type) || form.id" class="receipt-card">
    <template v-if="['stock', 'presale'].includes(form.order_type)">
    <div class="card-title">{{ form.order_type === 'presale' ? '首次收款' : '本次回款' }} <StatusBadge effect="plain" type="warning" size="small">{{ intentLabel }}</StatusBadge></div>
    <p class="receipt-hint">{{ intentHint }}</p>
    <!-- 小满回款方式在其接口中非必填，且口径与内部付款方式不同；自动回款单统一按 Other 提交 -->
    <p class="method-note">小满回款方式默认按 Other 提交（小满侧非必填），无需选择。</p>
    <template v-if="form.order_type === 'presale' && form.receipt_draft">
      <el-form-item label="收款用途" required><el-select v-model="form.receipt_draft.purpose" :disabled="frozen">
        <el-option value="presale_advance" label="预付货款 · 每批商品款和运费均可扣减" />
        <el-option value="presale_deposit" label="定金 · 仅人工确认最后一批时抵扣" />
      </el-select></el-form-item>
      <p class="receipt-hint">产品未确定时可先保存预售单并登记实际到账款，发货前填写本批明细。原回款不会因修改明细而重复生成或重新计算手续费。</p>
    </template>
    <ReceiptFields v-if="form.receipt_draft" :form="form.receipt_draft" :currency="form.currency"
      :readonly="frozen" :hide-proofs="canEditProofs" :hide-remark="canEditProofs" :show-charge="form.order_type === 'presale'" hide-payment-type @uploading="v => form.receipt_uploading = v" />
    <InvoiceConvertedProofs v-if="canEditProofs" :key="`${form.receipt_draft.receipt_id}:${form.receipt_draft.receipt_version}`" :receipt-id="form.receipt_draft.receipt_id"
      :locked="locked || form.receipt_action_open || form.receipt_action_busy"
      @saved="(id, ids) => { if (form.receipt_draft?.receipt_id === id) form.receipt_draft.attachment_ids = ids }"
      @updated="row => applySubmittedReceipt(form, row)"
      @remark-editing="value => form.receipt_remark_editing = value"
      @remark-saving="value => form.receipt_remark_saving = value"
      @uploading="value => form.receipt_uploading = value"
      @dirty="value => form.receipt_proof_dirty = value" />
    <p v-if="form.receipt_draft?.last_error" class="receipt-error" role="alert">{{ form.receipt_draft.last_error }}</p>
    <p v-if="form.receipt_draft?.eligible === false" class="receipt-hint">此单为历史库存单，补传凭证后可同步订单，已有回款不会自动补建。</p>
    </template>
    <InvoiceReceiptActions v-if="form.id" :form="form" :total="total" />
  </section>
</template>
<script setup>
import { computed, watch } from 'vue'
import ReceiptFields from '@/views/receipt/ReceiptFields.vue'
import InvoiceConvertedProofs from './InvoiceConvertedProofs.vue'
import InvoiceReceiptActions from './InvoiceReceiptActions.vue'
import { nextDraftAmount, applySubmittedReceipt } from '../composables/invoiceReceiptState'
import { useAuthStore } from '@/stores/auth'
import { currentBeijingDate } from '@/utils/datetime'
const props = defineProps({ form: { type: Object, required: true }, total: { type: Number, required: true }, locked: Boolean })
const frozen = computed(() => props.form.receipt_draft?.status && props.form.receipt_draft.status !== 'draft')
const intentLabel = computed(() => ({ armed: '订单同步中', ready: '等待生成回款', converted: '原回款已生成' })[props.form.receipt_draft?.status] || '同步前必填')
const intentHint = computed(() => ({
  armed: '订单同步正在处理或等待恢复，暂不能修改首次回款，请先查看订单同步结果。',
  ready: '首次回款正在等待生成，请稍后刷新；生成后按回款单状态修正或核对。',
  converted: '本次回款已生成，金额显示原回款的当前记录；订单重新同步不会重复建款。',
})[props.form.receipt_draft?.status] || '上传实际到账截图；订单完整同步后自动生成回款单。回款金额默认随预付款填入，可手改；可先保存草稿。')
const auth = useAuthStore()
const canEditProofs = computed(() => props.form.receipt_draft?.status === 'converted' &&
  props.form.receipt_draft?.receipt_status === 'active' && props.form.receipt_draft?.receipt_id && auth.hasPermission('receipt:write'))
watch(() => props.form.receipt_draft, value => {
  if (!value) props.form.receipt_draft = { amount: props.form.order_type === 'presale' ? null : props.form.internal_received > 0 ? props.form.internal_received : null,
    collection_date: currentBeijingDate(), payment_type: 'Other',
    purpose: props.form.order_type === 'presale' ? 'presale_advance' : 'ordinary',
    bank_charge: 0, attachment_ids: [], remark: '', status: 'draft' }
}, { immediate: true })
// 回款金额随预付款自动填入（2026-09-23）：只跟随未被手改过的草稿金额
watch(() => [props.form.id, props.form.internal_received], ([id, value], [previousId, previous]) => {
  const draft = props.form.receipt_draft
  if (id === previousId && draft) {
    draft.amount = nextDraftAmount(draft, previous, value, props.form.order_type)
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
