<template>
  <el-dialog :model-value="modelValue" title="登记本地收款" width="640px" :show-close="!command.pending.value && !uploading" :close-on-click-modal="!command.pending.value && !uploading" :close-on-press-escape="!command.pending.value && !uploading" @update:model-value="$emit('update:modelValue', $event)">
    <el-form label-position="top" :disabled="command.pending.value">
      <el-form-item label="本地客户"><NativeCustomerPicker v-model="form.local_customer_id" mode="finance" :disabled="command.pending.value" /></el-form-item>
      <el-form-item label="收款账户"><el-select v-model="form.bank_account_id" filterable @change="selectAccount"><el-option v-for="row in activeAccounts" :key="row.id" :value="row.id" :label="`${row.name} · ${row.currency}`" /></el-select></el-form-item>
      <el-form-item label="银行流水号"><el-input v-model="form.bank_reference" maxlength="128" /></el-form-item>
      <div class="finance-form-grid"><el-form-item :label="`付款总额（${form.currency || '先选账户'}）`"><el-input v-model="form.gross_amount" inputmode="decimal" /></el-form-item><el-form-item label="银行实际扣费"><el-input v-model="form.actual_bank_fee" inputmode="decimal" /></el-form-item></div>
      <el-form-item label="到账日期"><el-date-picker v-model="form.collection_date" value-format="YYYY-MM-DD" type="date" /></el-form-item>
      <el-form-item label="付款方式"><el-select v-model="form.payment_type"><el-option v-for="(label, key) in paymentTypes" :key="key" :value="key" :label="label" /></el-select></el-form-item>
      <el-form-item label="备注"><el-input v-model="form.remark" type="textarea" maxlength="500" /></el-form-item>
      <el-form-item label="付款凭证"><ReceiptProofs v-model="form.attachment_ids" :readonly="command.pending.value" @uploading="uploading = $event" /></el-form-item>
    </el-form>
    <ListPageStatus :error="reference.errorMessage.value" :has-data="reference.hasData.value" :paged="false" @retry="reference.load()" />
    <el-alert v-if="command.failure.value" type="error" :title="command.failure.value" :closable="false" show-icon />
    <template #footer><div class="dialog-footer"><GlassButton :disabled="command.pending.value || uploading" @click="$emit('update:modelValue', false)">返回</GlassButton><GlassButton v-permission="'receipt:write'" variant="primary" :loading="command.pending.value" :disabled="uploading || reference.loading.value || !!reference.error.value" @click="submit">登记收款</GlassButton></div></template>
  </el-dialog>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { getFinanceReference, registerPayment } from '@/api/nativeFinance'
import { useAsyncResource } from '@/composables/useAsyncResource'
import NativeCustomerPicker from '@/views/invoice/native/components/NativeCustomerPicker.vue'
import ReceiptProofs from '@/views/receipt/ReceiptProofs.vue'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { useNativeCommand } from '../useNativeCommand'
import { requireAmount, toUnits } from '../decimal'
import { paymentTypes } from '../labels'
const props = defineProps({ modelValue: Boolean }), emit = defineEmits(['update:modelValue', 'saved'])
const command = useNativeCommand(), uploading = ref(false), form = ref({})
const reference = useAsyncResource(async (_, { signal }) => (await getFinanceReference({ signal, suppressToast: true })).data)
const activeAccounts = computed(() => (reference.data.value?.accounts || []).filter(row => row.active && reference.data.value.currencies.some(c => c.code === row.currency && c.active)))
function selectAccount(id) { form.value.currency = activeAccounts.value.find(row => row.id === id)?.currency || '' }
watch(form, command.reset, { deep: true, flush: 'sync' })
watch(() => props.modelValue, open => { if (open) { form.value = { local_customer_id: null, bank_account_id: null, bank_reference: '', currency: '', gross_amount: '', actual_bank_fee: '0.00', collection_date: currentBeijingDate(), payment_type: 'bank_transfer', remark: '', attachment_ids: [] }; command.reset(); reference.load() } })
async function submit() {
  if (uploading.value) return
  const result = await command.run({ payload: () => {
    const row = form.value
    if (!row.local_customer_id || !activeAccounts.value.some(a => a.id === row.bank_account_id)) throw new Error('请选择客户和启用的收款账户')
    if (!row.bank_reference.trim() || !row.collection_date) throw new Error('请填写流水号和到账日期')
    const gross = requireAmount(row.gross_amount, '付款总额', { allowZero: false }), fee = requireAmount(row.actual_bank_fee, '银行扣费')
    if (toUnits(fee) >= toUnits(gross)) throw new Error('银行扣费必须小于付款总额')
    return { ...row, gross_amount: gross, actual_bank_fee: fee, bank_reference: row.bank_reference.trim() }
  }, send: registerPayment })
  if (result.ok) { msgSuccess('登记收款'); emit('update:modelValue', false); emit('saved', result.data) }
}
</script>
<style scoped>.finance-form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: var(--space-4); }</style>
