<template>
  <el-dialog :model-value="modelValue" title="新建本地生产批次" width="760px" :show-close="!command.pending.value" :close-on-click-modal="!command.pending.value" :close-on-press-escape="!command.pending.value" @update:model-value="$emit('update:modelValue', $event)">
    <el-form label-position="top" :disabled="command.pending.value">
      <el-form-item label="批次号（必填）"><el-input v-model="form.batch_no" maxlength="64" /></el-form-item>
      <div v-for="(line, index) in form.items" :key="line._key" class="production-line">
        <div class="action-bar"><strong>生产明细 {{ index + 1 }}</strong><GlassButton variant="link" :disabled="command.pending.value || form.items.length === 1" @click="removeLine(index)">移除</GlassButton></div>
        <div class="production-fields">
          <el-form-item label="产品 SKU（必选）"><SkuPicker v-model="line.local_sku_id" :disabled="command.pending.value" /></el-form-item>
          <el-form-item label="生产件数（必填）"><el-input-number v-model="line.quantity" :min="1" :max="2147483647" :precision="0" /></el-form-item>
          <el-form-item label="工序路线"><el-select class="production-field-control" v-model="line.process_route_id" clearable placeholder="可选，未绑定时登记实际完工"><el-option v-for="entry in reference.data.value?.process_routes || []" :key="entry.id" :value="entry.id" :label="entry.name" /></el-select></el-form-item>
          <el-form-item label="预计交付日期"><el-date-picker class="production-field-control" v-model="line.expected_delivery_date" type="date" value-format="YYYY-MM-DD" /></el-form-item>
        </div>
        <el-form-item label="明细备注"><el-input v-model="line.remark" maxlength="500" /></el-form-item>
      </div>
      <GlassButton left-icon="Plus" :disabled="command.pending.value || form.items.length >= 100" @click="addLine">增加生产明细</GlassButton>
      <el-form-item label="批次备注"><el-input v-model="form.remark" type="textarea" maxlength="500" /></el-form-item>
    </el-form>
    <ListPageStatus :error="reference.errorMessage.value" :loading="reference.loading.value" :has-data="reference.hasData.value" :paged="false" @retry="reference.load()" />
    <el-alert v-if="command.failure.value" :title="command.failure.value" type="error" :closable="false" show-icon />
    <template #footer><div class="dialog-footer"><GlassButton :disabled="command.pending.value" @click="$emit('update:modelValue', false)">返回</GlassButton><GlassButton v-permission="'production:write'" variant="primary" :loading="command.pending.value" @click="submit">创建生产批次</GlassButton></div></template>
  </el-dialog>
</template>
<script setup>
import { ref, watch } from 'vue'
import SkuPicker from '@/views/inventory/components/SkuPicker.vue'
import { getNativeProductionReference, createNativeProduction } from '@/api/nativeProduction'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useNativeCommand } from '@/views/finance/native/useNativeCommand'
import { msgSuccess } from '@/utils/feedback'
const props = defineProps({ modelValue: Boolean }), emit = defineEmits(['update:modelValue', 'saved'])
const command = useNativeCommand(), form = ref({ batch_no: '', remark: '', items: [] })
let serial = 0
function newLine() { return { _key: ++serial, local_sku_id: null, quantity: 1, process_route_id: null, expected_delivery_date: null, remark: '' } }
const reference = useAsyncResource(async (_, { signal }) => (await getNativeProductionReference({ signal, suppressToast: true })).data)
function addLine() { if (!command.pending.value && form.value.items.length < 100) form.value.items.push(newLine()) }
function removeLine(index) { if (!command.pending.value && form.value.items.length > 1) form.value.items.splice(index, 1) }
watch(() => props.modelValue, visible => { if (visible) { if (!form.value.items.length) form.value.items = [newLine()]; reference.load() } })
async function submit() {
  const result = await command.run({ payload: () => {
    if (!form.value.batch_no.trim()) throw new Error('请填写批次号')
    if (form.value.items.some(row => !row.local_sku_id || !Number.isInteger(row.quantity) || row.quantity <= 0)) throw new Error('请选择每行产品，并填写正整数件数')
    return { ...form.value, batch_no: form.value.batch_no.trim(), items: form.value.items.map(({ _key, ...row }) => row) }
  }, send: createNativeProduction })
  if (result.ok) { form.value = { batch_no: '', remark: '', items: [] }; msgSuccess('创建生产批次'); emit('update:modelValue', false); emit('saved', result.data) }
}
</script>
<style scoped>
.production-line { padding: 16px; margin-bottom: 16px; border: 1px solid var(--el-border-color); border-radius: 12px; }
.production-fields { display: grid; grid-template-columns: minmax(0, 2fr) minmax(0, 1fr); gap: 0 16px; }
.production-field-control { width: 100%; }
@media (max-width: 600px) { .production-fields { grid-template-columns: minmax(0, 1fr); } }
</style>
