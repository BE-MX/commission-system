<template>
  <el-form-item label="在 AI 生图中使用">
    <el-switch :model-value="enabled" :disabled="!parameters" @update:model-value="updateStudio('enabled', $event)" />
    <div class="form-hint">启用后自动出现在 AI 生图的模型列表；同一型号可绑定不同预设。</div>
  </el-form-item>
    <el-form-item label="生图接口形式">
      <el-select :model-value="parameters?.api_style || 'images'" @update:model-value="update('api_style', $event)">
        <el-option label="Images（生成 / 编辑）" value="images" />
        <el-option label="Chat Completions（图片模型）" value="chat" />
      </el-select>
    </el-form-item>
  <template v-if="enabled">
    <el-form-item label="生图显示名称">
      <el-input :model-value="parameters?.studio?.label || ''" :maxlength="128" placeholder="留空则显示模型名称" @update:model-value="updateStudio('label', $event)" />
    </el-form-item>
    <el-form-item label="可选图片尺寸">
      <el-select :model-value="parameters?.studio?.sizes || ['1024x1024', '1024x1536', '1536x1024']" multiple filterable allow-create default-first-option class="image-option-select" @update:model-value="updateStudio('sizes', $event)">
        <el-option v-for="value in (parameters?.studio?.sizes || ['1024x1024', '1024x1536', '1536x1024'])" :key="value" :label="value" :value="value" />
      </el-select>
    </el-form-item>
    <el-form-item label="可选生成质量">
      <el-select :model-value="parameters?.studio?.qualities || ['low', 'medium', 'high']" multiple filterable allow-create default-first-option class="image-option-select" @update:model-value="updateStudio('qualities', $event)">
        <el-option v-for="value in (parameters?.studio?.qualities || ['low', 'medium', 'high'])" :key="value" :label="value" :value="value" />
      </el-select>
    </el-form-item>
    <div class="form-hint">图片链接的下载域名填入 download_hosts；供应商扩展参数填入 request_parameters。尺寸与质量以生图页面的本次选择为准。</div>
  </template>
</template>

<script setup>
import { computed } from 'vue'
const props = defineProps({ modelValue: { type: String, default: '{}' }, presetName: { type: String, default: '' } })
const emit = defineEmits(['update:modelValue'])
const parameters = computed(() => {
  try {
    const value = JSON.parse(props.modelValue)
    return value && !Array.isArray(value) && typeof value === 'object' ? value : null
  } catch { return null }
})
const enabled = computed(() => parameters.value?.studio?.enabled ?? (props.presetName === 'design_image_generation' || props.presetName.startsWith('design_image_generation_')))
function update(key, value) {
  if (!parameters.value) return
  emit('update:modelValue', JSON.stringify({ ...parameters.value, [key]: value }, null, 2))
}
function updateStudio(key, value) {
  update('studio', { ...parameters.value?.studio, [key]: value })
}
</script>

<style scoped>
.image-option-select { width: 100%; }
</style>
