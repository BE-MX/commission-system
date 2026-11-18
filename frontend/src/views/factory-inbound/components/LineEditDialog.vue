<template>
  <el-dialog :model-value="open" :title="line ? '修正第 ' + line.line_no + ' 行' : '手工录入明细'"
    width="480px" append-to-body @close="$emit('close')">
    <el-form v-if="open" label-position="top" @submit.prevent="submit">
      <div class="fields">
        <el-form-item v-for="field in textFields" :key="field.key" :label="field.label">
          <el-input v-model="form[field.key]" maxlength="128" />
        </el-form-item>
        <el-form-item label="数量">
          <el-input-number v-model="form.quantity" class="quantity-input" :min="1" :max="1000000" :precision="0" controls-position="right" />
        </el-form-item>
        <el-form-item label="数量单位">
          <el-select v-model="form.quantity_unit" allow-create filterable clearable>
            <el-option v-for="unit in ['条', '片', '根', '件']" :key="unit" :label="unit" :value="unit" />
          </el-select>
        </el-form-item>
        <el-form-item label="行类型">
          <el-select v-model="form.line_type" placeholder="选择行类型">
            <el-option v-for="type in types" :key="type.code" :label="type.label" :value="type.code" />
          </el-select>
        </el-form-item>
      </div>
    </el-form>
    <template #footer>
      <GlassButton @click="$emit('close')">取消</GlassButton>
      <GlassButton variant="primary" :loading="busy" :disabled="!form.line_type" @click="submit">保存并匹配</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'

const props = defineProps({ open: Boolean, line: Object, types: Array, busy: Boolean })
const emit = defineEmits(['close', 'save'])
const textFields = [
  { key: 'order_ref_raw', label: '生产单号' }, { key: 'grade_raw', label: '等级' },
  { key: 'process_raw', label: '工艺' }, { key: 'length_raw', label: '长度（英寸）' },
  { key: 'color_raw', label: '颜色' }, { key: 'weight_raw', label: '克重（g）' },
]
const fieldNames = [...textFields.map(({ key }) => key), 'quantity', 'quantity_unit', 'line_type']
const form = ref({})
watch(() => props.open, open => {
  if (open) form.value = { ...props.line?.values }
}, { immediate: true })
function submit() {
  const values = {}
  for (const name of fieldNames) {
    const current = form.value[name]
    const value = typeof current === 'string' ? current.trim() || null : current ?? null
    if (!props.line || value !== (props.line.values[name] ?? null)) values[name] = value
  }
  if (Object.keys(values).length) emit('save', values)
  else emit('close')
}
</script>

<style scoped>
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
.quantity-input { width: 100%; }
</style>
