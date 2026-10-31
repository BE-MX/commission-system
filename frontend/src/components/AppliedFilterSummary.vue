<template>
  <div v-if="items.length" class="applied-filters" role="group" aria-label="当前查询条件">
    <span class="applied-filters-label">当前查询</span>
    <button v-for="item in items" :key="item.key" type="button" class="applied-filter"
      :aria-label="`移除${item.label}：${item.value}`" :title="`${item.label}：${item.value}`" @click="emit('remove', item.key)">
      <span>{{ item.label }}：{{ item.value }}</span><el-icon aria-hidden="true"><Close /></el-icon>
    </button>
  </div>
</template>
<script setup>
import { Close } from '@element-plus/icons-vue'
defineProps({ items: { type: Array, default: () => [] } })
const emit = defineEmits(['remove'])
</script>
<style scoped>
.applied-filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.applied-filters-label { color: var(--text-secondary); font-size: 12px; }
.applied-filter { display: inline-flex; align-items: center; gap: 6px; min-height: 28px; max-width: 100%; padding: 3px 8px; border: 1px solid var(--border-color); border-radius: 6px; color: var(--text-primary); background: var(--card-bg); font: inherit; font-size: 12px; cursor: pointer; }
.applied-filter > span { max-width: 320px; overflow: hidden; white-space: nowrap; text-overflow: ellipsis; }
.applied-filter:hover { border-color: var(--color-primary); background: var(--color-primary-light); }
.applied-filter:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 2px; }
@media (pointer: coarse) { .applied-filter { min-height: 44px; } }
</style>
