<template>
  <div class="item-group-bar">
    <div class="item-group-navigation">
      <div class="item-group-tabs" role="tablist" aria-label="产品明细分组">
        <button
          type="button"
          role="tab"
          :aria-selected="activeKey === ALL_ITEM_GROUPS"
          :class="['item-group-tab', { 'is-active': activeKey === ALL_ITEM_GROUPS }]"
          @click="$emit('update:activeKey', ALL_ITEM_GROUPS)"
        >
          全部明细 <span class="item-group-count">{{ allCount }}</span>
        </button>
        <button
          v-for="group in groups"
          :key="group.key"
          type="button"
          role="tab"
          :aria-selected="activeKey === group.key"
          :title="group.name"
          :class="['item-group-tab', { 'is-active': activeKey === group.key }]"
          @click="$emit('update:activeKey', group.key)"
        >
          <span class="item-group-name">{{ group.name }}</span>
          <span class="item-group-count">{{ counts[group.key] || 0 }}</span>
        </button>
      </div>
      <el-button class="item-group-create" @click="$emit('create')">
        <el-icon><Plus /></el-icon>新建分组
      </el-button>
    </div>
    <div v-if="activeGroup || selectedCount" class="item-group-actions">
      <template v-if="activeGroup">
        <span class="item-group-current">当前：{{ activeGroup.name }}</span>
        <el-button link type="primary" @click="$emit('rename', activeGroup.key)">重命名</el-button>
        <el-button v-if="!counts[activeGroup.key]" link type="danger" @click="$emit('delete', activeGroup.key)">删除空组</el-button>
      </template>
      <el-select
        v-if="selectedCount && groups.length"
        class="item-group-move"
        :model-value="null"
        placeholder="移动所选到分组"
        @change="key => $emit('move', key)"
      >
        <el-option v-for="group in groups" :key="group.key" :label="group.name" :value="group.key" />
      </el-select>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { Plus } from '@element-plus/icons-vue'
import { ALL_ITEM_GROUPS } from '../composables/useInvoiceItemGroups.js'

const props = defineProps({
  groups: { type: Array, default: () => [] },
  counts: { type: Object, default: () => ({}) },
  activeKey: { type: String, required: true },
  allCount: { type: Number, default: 0 },
  selectedCount: { type: Number, default: 0 },
})
defineEmits(['update:activeKey', 'create', 'rename', 'delete', 'move'])
const activeGroup = computed(() => props.groups.find(group => group.key === props.activeKey) || null)
</script>

<style scoped>
.item-group-bar { display: grid; gap: 8px; margin-bottom: 10px; }
.item-group-navigation { display: flex; align-items: center; gap: 8px; min-width: 0; }
.item-group-tabs { display: flex; flex: 1; gap: 4px; min-width: 0; overflow-x: auto; padding: 2px; }
.item-group-tab { display: inline-flex; align-items: center; gap: 6px; flex: none; max-width: 220px; padding: 5px 10px;
  border: 1px solid var(--border-color); border-radius: 6px; background: var(--card-bg); color: var(--text-secondary);
  font: inherit; font-size: 12px; line-height: 20px; cursor: pointer; white-space: nowrap; }
.item-group-tab.is-active { border-color: var(--color-primary); background: var(--color-primary-light); color: var(--color-primary-text); font-weight: 600; }
.item-group-tab:focus-visible { outline: 2px solid var(--color-primary-glow); outline-offset: 1px; }
.item-group-name { overflow: hidden; text-overflow: ellipsis; }
.item-group-count { min-width: 18px; padding: 0 4px; border-radius: 4px; background: var(--table-header-bg); color: var(--text-muted);
  font-variant-numeric: tabular-nums; text-align: center; }
.item-group-create { flex: none; }
.item-group-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 4px 10px; min-height: 24px; }
.item-group-current { max-width: 280px; overflow: hidden; text-overflow: ellipsis; color: var(--text-muted); font-size: 12px; white-space: nowrap; }
.item-group-move { width: 170px; margin-left: auto; }
@media (hover: hover) and (pointer: fine) {
  .item-group-tab:hover { border-color: var(--color-primary); color: var(--color-primary-text); }
}
</style>
