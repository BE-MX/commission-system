<template>
  <el-dialog :model-value="modelValue" :title="operation === 'confirm' ? '确认本地订单' : '取消本地订单'" width="480px"
    :close-on-click-modal="!command.pending.value" :close-on-press-escape="!command.pending.value" :show-close="!command.pending.value" @update:model-value="$emit('update:modelValue', $event)">
    <p>订单 {{ invoice?.invoice_no }} · 当前读取版本 {{ form.expected_version }}</p>
    <p>{{ operation === 'confirm' ? '确认后生成本地应收，现货订单同时预占所选仓库的合格库存。' : '取消将释放未履约库存责任；有收款、生产或发货批次的订单须先处理关联业务。' }}</p>
    <el-form :model="form" label-position="top" :disabled="command.pending.value">
      <el-form-item v-if="operation === 'confirm' && invoice?.order_type === 'stock'" label="供货仓库（必选）"><el-select v-model="form.warehouse_id" filterable placeholder="选择仓库"><el-option v-for="warehouse in reference.data.value?.warehouses || []" :key="warehouse.id" :label="warehouse.name" :value="warehouse.id" /></el-select></el-form-item>
      <el-form-item label="操作原因（必填）"><el-input v-model="form.reason" type="textarea" maxlength="500" /></el-form-item>
    </el-form>
    <ListPageStatus :error="reference.errorMessage.value" :has-data="reference.hasData.value" :paged="false" @retry="reference.load()" />
    <el-alert v-if="command.failure.value" type="error" :title="command.failure.value" :closable="false" show-icon />
    <p v-if="command.failure.value">输入已保留。版本冲突请关闭后刷新订单，重试原请求不会重复记账。</p>
    <template #footer><div class="dialog-footer"><GlassButton :disabled="command.pending.value" @click="$emit('update:modelValue', false)">返回</GlassButton><GlassButton v-permission="'invoice:write'" :variant="operation === 'cancel' ? 'danger' : 'primary'" :loading="command.pending.value" @click="submit">{{ operation === 'confirm' ? '确认订单' : '确认取消' }}</GlassButton></div></template>
  </el-dialog>
</template>
<script setup>
import { ref, watch } from 'vue'
import { getNativeInvoiceReference, confirmNativeInvoice, cancelNativeInvoice } from '@/api/nativeInvoice'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
const props = defineProps({ modelValue: Boolean, invoice: Object, operation: String })
const emit = defineEmits(['update:modelValue', 'saved'])
const command = useNativeCommand(), form = ref({ expected_version: 0, reason: '', warehouse_id: null })
const reference = useAsyncResource(async (_, { signal }) => (await getNativeInvoiceReference({ signal, suppressToast: true })).data)
watch(form, command.reset, { deep: true, flush: 'sync' })
watch(() => props.modelValue, visible => { if (visible) { form.value = { expected_authority_epoch: props.invoice.authority_epoch, expected_version: props.invoice.commerce_version, reason: '', warehouse_id: null }; command.reset(); if (props.operation === 'confirm' && props.invoice.order_type === 'stock') reference.load() } })
async function submit() {
  const submitted = props.invoice, operation = props.operation
  const result = await command.run({
    payload: () => {
      if (!form.value.reason.trim()) throw new Error('请填写操作原因')
      if (props.operation === 'confirm' && props.invoice.order_type === 'stock' && !form.value.warehouse_id) throw new Error('请选择供货仓库')
      return { ...form.value, reason: form.value.reason.trim() }
    },
    confirm: props.operation === 'cancel' ? () => confirmDanger('取消订单', props.invoice.invoice_no, '原订单及历史凭证保留。') : undefined,
    send: body => (operation === 'confirm' ? confirmNativeInvoice : cancelNativeInvoice)(submitted.id, body),
  })
  if (result.ok) { msgSuccess(props.operation === 'confirm' ? '确认订单' : '取消订单'); emit('update:modelValue', false); emit('saved', result.data) }
}
</script>
