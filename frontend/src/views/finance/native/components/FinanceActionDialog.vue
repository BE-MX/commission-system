<template>
  <el-dialog :model-value="modelValue" :title="titles[operation]" width="480px" :show-close="!command.pending.value" :close-on-click-modal="!command.pending.value" :close-on-press-escape="!command.pending.value" @update:model-value="$emit('update:modelValue', $event)">
    <p>{{ target?.batch_no || target?.invoice_no || target?.label }} · 当前版本 {{ target?.version }}</p>
    <el-form label-position="top" :disabled="command.pending.value">
      <el-form-item :label="operation === 'close' ? '关账截止日（含当日）' : '业务日期'"><el-date-picker v-model="form.business_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item v-if="['refund', 'reverse', 'adjust'].includes(operation)" :label="operation === 'adjust' ? '应收调整额（正数增加，负数减少）' : operation === 'reverse' ? '冲回金额（留空冲回全部剩余金额）' : '退款金额'"><el-input v-model="form.amount" inputmode="decimal" /></el-form-item>
      <el-form-item v-if="operation === 'refund'" label="退款银行流水号"><el-input v-model="form.bank_reference" maxlength="128" /></el-form-item>
      <el-form-item v-if="operation === 'due'" label="应收到期日"><el-date-picker v-model="form.due_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
      <el-form-item label="操作原因（必填）"><el-input v-model="form.reason" type="textarea" maxlength="500" /></el-form-item>
    </el-form>
    <p v-if="operation === 'close'">截止日及之前的业务日期将禁止新增或变更财务记账。请完成对账后关账。</p>
    <el-alert v-if="command.failure.value" type="error" :title="command.failure.value" :closable="false" show-icon />
    <p v-if="command.failure.value">输入已保留。版本冲突请返回并刷新后重试。</p>
    <template #footer><div class="dialog-footer"><GlassButton :disabled="command.pending.value" @click="$emit('update:modelValue', false)">返回</GlassButton><GlassButton v-permission="operation === 'void' ? 'receipt:write' : 'receipt:admin'" variant="primary" :loading="command.pending.value" @click="submit">{{ titles[operation] }}</GlassButton></div></template>
  </el-dialog>
</template>
<script setup>
import { ref, watch } from 'vue'
import { confirmPayment, voidPayment, refundPayment, reverseAllocation, adjustReceivable, setReceivableDueDate, closeFinancePeriod } from '@/api/nativeFinance'
import { currentBeijingDate } from '@/utils/datetime'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import { useNativeCommand } from '../useNativeCommand'
import { requireAmount, toUnits } from '../decimal'
const props = defineProps({ modelValue: Boolean, operation: String, target: Object })
const emit = defineEmits(['update:modelValue', 'saved'])
const titles = { confirm: '财务确认到账', void: '作废收款登记', refund: '登记实际退款', reverse: '冲回核销', adjust: '调整应收', due: '修改到期日', close: '确认关账' }
const command = useNativeCommand(), form = ref({})
watch(form, command.reset, { deep: true, flush: 'sync' })
watch(() => props.modelValue, open => { if (open) { form.value = { business_date: currentBeijingDate(), reason: '', amount: '', bank_reference: '', due_date: props.target?.due_date || '' }; command.reset() } })
async function submit() {
  const result = await command.run({ payload: () => {
    const source = form.value, action = props.operation, target = props.target
    if (!source.business_date || !source.reason.trim()) throw new Error('请填写业务日期和操作原因')
    const body = { expected_version: target.version, business_date: source.business_date, reason: source.reason.trim() }
    if (['refund', 'adjust'].includes(action) || (action === 'reverse' && source.amount.trim())) body.amount = requireAmount(source.amount, '金额', { allowNegative: action === 'adjust', allowZero: false })
    if (action === 'refund') { if (!source.bank_reference.trim()) throw new Error('请填写退款银行流水号'); body.bank_reference = source.bank_reference.trim(); if (toUnits(body.amount) > toUnits(target.available_amount)) throw new Error('退款金额不能超过付款可用余额') }
    if (action === 'reverse' && body.amount && toUnits(body.amount) > toUnits(target.effective_amount)) throw new Error('冲回金额不能超过剩余有效金额')
    if (['adjust', 'due'].includes(action)) body.invoice_id = target.invoice_id
    if (action === 'due') { if (!source.due_date) throw new Error('请选择到期日'); body.due_date = source.due_date }
    return body
  }, confirm: ['void', 'refund', 'reverse', 'close'].includes(props.operation) ? () => confirmDanger(titles[props.operation], props.target?.batch_no || '', '操作会记录不可删除的业务凭证。') : undefined,
  send: body => props.operation === 'close' ? closeFinancePeriod(body) : ({ confirm: confirmPayment, void: voidPayment, refund: refundPayment, reverse: reverseAllocation, adjust: adjustReceivable, due: setReceivableDueDate }[props.operation])(props.target.id, body) })
  if (result.ok) { msgSuccess(titles[props.operation]); emit('update:modelValue', false); emit('saved', result.data) }
}
</script>
