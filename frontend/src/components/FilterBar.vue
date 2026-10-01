<template>
  <div class="toolbar filter-bar" role="search" :aria-label="label" @keydown.enter="handleEnter">
    <div class="filter-bar-fields"><slot /></div>
    <div class="filter-bar-actions">
      <GlassButton
        v-if="hasAdvanced"
        variant="ghost"
        :left-icon="expanded ? ArrowUp : ArrowDown"
        :aria-expanded="expanded"
        :aria-controls="advancedId"
        @click="expanded = !expanded"
      >{{ expanded ? '收起筛选' : '展开筛选' }}{{ advancedCount ? `（${advancedCount}）` : '' }}</GlassButton>
      <GlassButton variant="primary" :left-icon="Search" :loading="loading" @click="emit('search')">查询</GlassButton>
      <GlassButton :left-icon="RefreshLeft" @click="emit('reset')">重置</GlassButton>
    </div>
    <div v-if="hasAdvanced" v-show="expanded" :id="advancedId" class="filter-bar-advanced">
      <slot name="advanced" />
    </div>
    <p v-if="pending" class="filter-bar-notice" role="status">筛选条件已修改，查询后生效。</p>
    <div v-if="$slots.summary" class="filter-bar-summary"><slot name="summary" /></div>
  </div>
</template>

<script setup>
import { computed, getCurrentInstance, ref, useSlots } from 'vue'
import { ArrowDown, ArrowUp, RefreshLeft, Search } from '@element-plus/icons-vue'
import GlassButton from './GlassButton.vue'

const props = defineProps({
  label: { type: String, default: '列表筛选' },
  loading: Boolean,
  pending: Boolean,
  advancedCount: { type: Number, default: 0 },
  defaultExpanded: Boolean,
})
const emit = defineEmits(['search', 'reset'])
const slots = useSlots()
const hasAdvanced = computed(() => !!slots.advanced)
const expanded = ref(props.defaultExpanded)
const advancedId = `filter-bar-advanced-${getCurrentInstance().uid}`

function handleEnter(event) {
  // Enter selects an option/date or confirms IME input before it submits a query.
  if (props.loading || event.defaultPrevented || event.isComposing || event.keyCode === 229 || event.repeat) return
  const target = event.target
  if (target?.tagName !== 'INPUT' || target.closest?.('[role="combobox"], .el-select, .el-date-editor')) return
  event.preventDefault()
  emit('search')
}
</script>

<style scoped>
.filter-bar, .filter-bar-fields, .filter-bar-actions, .filter-bar-advanced {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  min-width: 0;
  --el-component-size: 36px;
}
.filter-bar-fields { max-width: 100%; }
.filter-bar-advanced, .filter-bar-summary, .filter-bar-notice { flex-basis: 100%; }
.filter-bar-advanced {
  padding-top: 10px;
  border-top: 1px dashed var(--border-color);
}
.filter-bar-notice { margin: 0; font-size: 12px; color: var(--text-secondary); }
.toolbar.filter-bar :deep(.filter-w-sm) { width: 160px; }
.toolbar.filter-bar :deep(.filter-w-md) { width: 200px; }
.toolbar.filter-bar :deep(.filter-w-lg) { width: 280px; }
.toolbar.filter-bar :deep(.filter-w-sm), .toolbar.filter-bar :deep(.filter-w-md), .toolbar.filter-bar :deep(.filter-w-lg) { flex: none; max-width: 100%; }
@media (max-width: 600px) {
  .filter-bar-fields, .filter-bar-advanced, .filter-bar-actions { width: 100%; }
  .toolbar.filter-bar :deep(.filter-w-sm), .toolbar.filter-bar :deep(.filter-w-md), .toolbar.filter-bar :deep(.filter-w-lg) { width: 100%; }
}
</style>
