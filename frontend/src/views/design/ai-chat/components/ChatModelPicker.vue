<template>
  <div class="model-picker">
    <el-select
      :model-value="modelValue" :disabled="disabled || !models.length" filterable
      placeholder="选择模型" aria-label="聊天模型" class="model-select"
      @update:model-value="emit('update:modelValue', $event)"
    >
      <el-option v-for="model in models" :key="model.preset_id" :value="model.preset_id" :label="model.label">
        <div class="model-option"><span>{{ model.label }}</span><small>{{ model.vision ? '图片 · 文本' : '文本' }}</small></div>
      </el-option>
    </el-select>
    <button type="button" class="model-refresh" :disabled="disabled" aria-label="刷新模型列表" title="刷新模型列表" @click="emit('refresh')">
      <el-icon><Refresh /></el-icon>
    </button>
  </div>
</template>

<script setup>
import { Refresh } from '@element-plus/icons-vue'
defineProps({ modelValue: { type: Number, default: null }, models: { type: Array, default: () => [] }, disabled: Boolean })
const emit = defineEmits(['update:modelValue', 'refresh'])
</script>

<style scoped>
.model-picker { display: flex; min-width: 0; align-items: center; gap: 4px; }
.model-select { width: 230px; max-width: 100%; }
.model-option { display: flex; align-items: center; justify-content: space-between; gap: 18px; }
.model-option small { color: var(--text-secondary); font-size: 11px; }
.model-refresh { display: grid; place-items: center; flex-shrink: 0; width: 32px; height: 32px; padding: 0; border: 0; border-radius: 8px; background: transparent; color: var(--text-secondary); cursor: pointer; }
.model-refresh:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
.model-refresh:disabled { opacity: .5; cursor: not-allowed; }
@media (hover: hover) and (pointer: fine) { .model-refresh:hover { background: var(--color-primary-light); } }
@media (max-width: 640px) { .model-select { width: 100%; } .model-picker { width: 100%; } }
</style>
