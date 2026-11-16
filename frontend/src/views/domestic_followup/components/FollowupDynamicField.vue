<template>
  <el-form-item :label="field.label" class="dynamic-field">
    <el-input v-if="field.kind === 'text'" :model-value="modelValue || ''" :placeholder="field.hint" @update:model-value="emitValue" />
    <el-input v-else-if="field.kind === 'textarea'" :model-value="modelValue || ''" type="textarea" :rows="3" :placeholder="field.hint" @update:model-value="emitValue" />
    <el-select v-else-if="field.kind === 'select'" :model-value="modelValue" clearable :placeholder="field.hint || '请选择'" class="full" @update:model-value="emitValue">
      <el-option v-for="option in options" :key="option" :label="option" :value="option" />
    </el-select>
    <el-select v-else-if="field.kind === 'multiselect'" :model-value="modelValue || []" multiple :placeholder="field.hint || '请选择'" class="full" @update:model-value="emitValue">
      <el-option v-for="option in options" :key="option" :label="option" :value="option" />
    </el-select>
    <el-date-picker v-else-if="field.kind === 'date'" :model-value="modelValue" type="date" value-format="YYYY-MM-DD" class="full" @update:model-value="emitValue" />
    <div v-else-if="field.kind === 'amount'" class="amount-fields">
      <el-input :model-value="amount.amount" placeholder="金额 / 原始表达" @update:model-value="value => updateAmount('amount', value)" />
      <el-input :model-value="amount.unit" placeholder="币种 / 单位" @update:model-value="value => updateAmount('unit', value)" />
      <el-select :model-value="amount.meaning" clearable placeholder="未确认" @update:model-value="value => updateAmount('meaning', value)">
        <el-option v-for="option in options" :key="option" :label="option" :value="option" />
      </el-select>
    </div>
    <el-input v-else :model-value="modelValue || ''" :placeholder="field.hint || '何时或何事后核实'" @update:model-value="emitValue" />
    <p v-if="field.hint" class="field-hint">{{ field.hint }}</p>
  </el-form-item>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { getDictItems } from '@/api/system'
import { apiError } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'
import { dictOptionLabels } from '../followupDynamicOptions'

const props = defineProps({ field: { type: Object, required: true }, modelValue: { type: [String, Number, Array, Object], default: null }, dicts: { type: Object, default: () => ({}) } })
const emit = defineEmits(['update:modelValue'])
const remoteOptions = ref([])
let dictRequest = 0
watch(() => props.field.options?.dict, async type => {
  const request = ++dictRequest
  remoteOptions.value = []
  if (!type) return
  try {
    const response = await getDictItems(type, true, { suppressToast: true })
    if (request === dictRequest) remoteOptions.value = dictOptionLabels(response.data)
  } catch (e) { if (request === dictRequest) msgError(apiError(e, '字典选项加载失败'), e) }
}, { immediate: true })
const options = computed(() => props.field.options?.inline
  || (remoteOptions.value.length ? remoteOptions.value : props.dicts[props.field.options?.dict]) || [])
const amount = computed(() => typeof props.modelValue === 'object' && props.modelValue ? props.modelValue : {})
const emitValue = value => emit('update:modelValue', value)
function updateAmount(key, value) { emit('update:modelValue', { ...amount.value, [key]: value }) }
</script>

<style scoped>
.full { width: 100%; }
.amount-fields { display: grid; grid-template-columns: 1.1fr .8fr 1.2fr; gap: 8px; width: 100%; }
.field-hint { margin: 4px 0 0; color: var(--text-secondary); font-size: 12px; }
@media (max-width: 600px) { .amount-fields { grid-template-columns: 1fr; } }
</style>
