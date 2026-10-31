<template>
  <el-dialog :model-value="modelValue" title="核销订单应收" width="640px" :show-close="!command.pending.value" :close-on-click-modal="!command.pending.value" :close-on-press-escape="!command.pending.value" @update:model-value="$emit('update:modelValue', $event)">
    <p>{{ payment?.customer_name }} · 可用余额 {{ formatNativeMoney(payment?.available_amount) }} {{ payment?.currency }}</p>
    <el-form label-position="top" :disabled="command.pending.value">
      <el-form-item label="本地订单（仅同客户、同币种）"><NativeOrderPicker v-model="form.invoice_id" :customer-id="payment?.local_customer_id" :currency="payment?.currency" :disabled="command.pending.value" /></el-form-item>
      <el-form-item label="应收项目"><el-select v-model="form.receivable_id" :loading="resource.loading.value" @change="changeTarget"><el-option v-for="row in targets" :key="row.id" :value="row.id" :label="`${receivableKinds[row.kind]} · 余额 ${formatNativeMoney(row.remaining_amount)}${row.settlement_id ? ' · 批次 #' + row.settlement_id : ''}`" /></el-select></el-form-item>
      <el-form-item label="资金用途"><el-radio-group v-model="form.purpose"><el-radio value="ordinary">普通 / 批次款</el-radio><el-radio v-if="resource.data.value?.invoice.order_type === 'presale' && selectedTarget?.kind === 'goods'" value="presale_deposit">预售首款</el-radio></el-radio-group></el-form-item>
      <el-form-item v-if="form.purpose !== 'presale_deposit'" label="结算批次（预售必选）"><el-select v-model="form.settlement_id" clearable><el-option v-for="row in settlements" :key="row.id" :value="row.id" :label="`${row.settlement_no} · 本批新增应收 ${formatNativeMoney(row.quote.new_payment_due)}`" /></el-select></el-form-item>
      <el-form-item label="核销金额"><el-input v-model="form.amount" inputmode="decimal" /></el-form-item>
      <el-form-item label="核销业务日期"><el-date-picker v-model="form.business_date" value-format="YYYY-MM-DD" type="date" /></el-form-item>
    </el-form>
    <ListPageStatus :error="resource.errorMessage.value" :has-data="resource.hasData.value" :paged="false" @retry="resource.load()" />
    <el-alert v-if="command.failure.value" type="error" :title="command.failure.value" :closable="false" show-icon />
    <p>合同费用按后端资金计划分摊，银行实际扣费不在这里重复扣除。</p>
    <template #footer><div class="dialog-footer"><GlassButton :disabled="command.pending.value" @click="$emit('update:modelValue', false)">返回</GlassButton><GlassButton v-permission="'receipt:write'" variant="primary" :loading="command.pending.value" :disabled="!resource.data.value || resource.loading.value || !!resource.error.value" @click="submit">确认核销</GlassButton></div></template>
  </el-dialog>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { getReceivables, allocatePayment } from '@/api/nativeFinance'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { currentBeijingDate } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import NativeOrderPicker from './NativeOrderPicker.vue'
import { useNativeCommand } from '../useNativeCommand'
import { formatNativeMoney, positive } from '../decimal'
import { receivableKinds } from '../labels'
import { allocationPayload } from '../allocation'
const props = defineProps({ modelValue: Boolean, payment: Object }), emit = defineEmits(['update:modelValue', 'saved'])
const command = useNativeCommand(), form = ref({})
const resource = useAsyncResource(async (id, { signal }) => (await getReceivables(id, { signal, suppressToast: true })).data)
const targets = computed(() => (resource.data.value?.items || []).filter(row => !row.cancelled && positive(row.remaining_amount)))
const selectedTarget = computed(() => targets.value.find(row => row.id === form.value.receivable_id))
const settlements = computed(() => (resource.data.value?.settlements || []).filter(row => row.state === 'awaiting_payment' && (selectedTarget.value?.kind !== 'freight' || !selectedTarget.value?.settlement_id || selectedTarget.value.settlement_id === row.id)))
function changeTarget() { form.value.purpose = 'ordinary'; form.value.settlement_id = selectedTarget.value?.settlement_id || null }
watch(form, command.reset, { deep: true, flush: 'sync' })
watch(() => props.modelValue, open => { if (open) { resource.clear(); form.value = { invoice_id: null, receivable_id: null, settlement_id: null, purpose: 'ordinary', amount: '', business_date: currentBeijingDate() }; command.reset() } })
watch(() => form.value.invoice_id, id => { form.value.receivable_id = null; form.value.settlement_id = null; form.value.purpose = 'ordinary'; resource.clear(); if (id) resource.load(id) })
async function submit() { const result = await command.run({ payload: () => allocationPayload(form.value, props.payment, resource.data.value), send: body => allocatePayment(props.payment.id, body) }); if (result.ok) { msgSuccess('核销应收'); emit('update:modelValue', false); emit('saved') } }
</script>
