<template>
  <div v-if="!config" class="form-hint">参数 JSON 格式有误，请先修正下方 JSON 后再编辑表单。</div>
  <el-form-item v-for="field in fields" :key="field.key" :label="field.label" :error="errors[field.key]">
    <el-input-number v-if="field.type === 'number'" :model-value="value(field.key)" :min="field.min" :max="field.max" :disabled="!config" controls-position="right" placeholder="继承默认" @update:model-value="update(field, $event)" />
    <el-select v-else-if="field.type === 'boolean'" :model-value="value(field.key)" :disabled="!config" clearable placeholder="继承默认" @update:model-value="update(field, $event)">
      <el-option label="启用" :value="true" /><el-option label="禁用" :value="false" />
    </el-select>
    <el-select v-else-if="field.options" :model-value="value(field.key)" :disabled="!config" clearable placeholder="继承默认" @update:model-value="update(field, $event)">
      <el-option v-for="option in field.options" :key="option" :label="option" :value="option" />
    </el-select>
    <el-input v-else-if="field.type === 'json'" :model-value="jsonValue(field.key)" type="textarea" :rows="2" :disabled="!config" placeholder="留空继承默认" @input="drafts[field.key] = $event; update(field, $event)" />
    <el-input v-else :model-value="value(field.key) || ''" :disabled="!config" placeholder="留空继承默认" @update:model-value="update(field, $event)" />
    <div v-if="field.hint" class="form-hint">{{ field.hint }}</div>
  </el-form-item>
</template>

<script setup>
import { computed, reactive, watch } from 'vue'
import { parseConfig, getConfigValue, setConfigValue } from '../aiConfigFields'
const props = defineProps({ modelValue: { type: String, default: '{}' }, fields: { type: Array, required: true } })
const emit = defineEmits(['update:modelValue', 'validity'])
const config = computed(() => parseConfig(props.modelValue))
const errors = reactive({})
const drafts = reactive({})
const value = key => getConfigValue(config.value, key)
const jsonValue = key => drafts[key] ?? (value(key) === undefined ? '' : JSON.stringify(value(key), null, 2))
function update(field, input) {
  try {
    const next = field.type === 'json' && input ? JSON.parse(input) : input
    const updated = setConfigValue(props.modelValue, field.key, next)
    delete errors[field.key]
    delete drafts[field.key]
    emit('update:modelValue', updated)
  } catch (error) { errors[field.key] = error.message || '请输入有效 JSON' }
  emit('validity', Object.keys(errors).length === 0)
}
watch(() => props.modelValue, () => {
  for (const key of Object.keys(drafts)) if (!errors[key]) delete drafts[key]
})
</script>

<style scoped>
.el-input-number, .el-select { width: 100%; }
.form-hint { color: var(--el-text-color-secondary); font-size: 12px; line-height: 1.6; margin-top: 4px; width: 100%; }
</style>
