<template>
  <!-- 表格工具四图标：刷新 → 列显示 → 密度 → 全屏，顺序固定 -->
  <div class="table-tools">
    <el-tooltip content="刷新" placement="top" :show-after="300">
      <GlassButton variant="ghost" :left-icon="Refresh" :loading="loading" aria-label="刷新" @click="emit('refresh')" />
    </el-tooltip>

    <el-popover v-if="configurableColumns.length" trigger="click" placement="bottom-end" width="200">
      <template #reference>
        <GlassButton variant="ghost" :left-icon="SetUp" aria-label="列显示设置" />
      </template>
      <div class="tools-panel">
        <div class="tools-panel-title">列显示</div>
        <el-checkbox
          v-for="column in configurableColumns"
          :key="column.key"
          :model-value="visibleKeys.includes(column.key)"
          :disabled="visibleColumnCount === 1 && visibleKeys.includes(column.key)"
          @change="toggleColumn(column.key)"
        >
          {{ column.label }}
        </el-checkbox>
        <GlassButton variant="link" class="tools-reset" aria-label="恢复默认列与密度" @click="restoreDefaults">恢复默认列与密度</GlassButton>
      </div>
    </el-popover>

    <el-popover trigger="click" placement="bottom-end" width="160">
      <template #reference>
        <GlassButton variant="ghost" :left-icon="Grid" aria-label="行密度" />
      </template>
      <div class="tools-panel">
        <div class="tools-panel-title">行密度</div>
        <el-radio-group
          :model-value="density"
          class="tools-density-group"
          @update:model-value="value => emit('update:density', value)"
        >
          <el-radio value="compact">紧凑</el-radio>
          <el-radio value="default">默认</el-radio>
          <el-radio value="comfort">宽松</el-radio>
        </el-radio-group>
      </div>
    </el-popover>

    <el-tooltip :content="fullscreen ? '退出全屏' : '全屏'" placement="top" :show-after="300">
      <GlassButton
        variant="ghost"
        :left-icon="fullscreen ? Switch : FullScreen"
        :aria-label="fullscreen ? '退出全屏' : '全屏'"
        @click="emit('fullscreen')"
      />
    </el-tooltip>
  </div>
</template>

<script setup>
import { FullScreen, Grid, Refresh, SetUp, Switch } from '@element-plus/icons-vue'
import { computed, watch } from 'vue'
import { DEFAULT_TABLE_DENSITY, normalizeTableColumns, resetTableColumnSubset } from '../utils/tableViewPreferences.js'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  visibleKeys: { type: Array, default: () => [] },
  density: { type: String, default: 'default' },
  fullscreen: { type: Boolean, default: false },
  loading: Boolean,
})
const emit = defineEmits(['refresh', 'fullscreen', 'update:visibleKeys', 'update:density'])
const configurableColumns = computed(() => normalizeTableColumns(props.columns))
const visibleColumnCount = computed(() => configurableColumns.value.filter(column => props.visibleKeys.includes(column.key)).length)

watch([configurableColumns, () => props.visibleKeys], () => {
  if (configurableColumns.value.length && !visibleColumnCount.value) {
    emit('update:visibleKeys', resetTableColumnSubset(props.visibleKeys, configurableColumns.value))
  }
}, { deep: true, immediate: true })

function restoreDefaults() {
  emit('update:visibleKeys', resetTableColumnSubset(props.visibleKeys, configurableColumns.value))
  emit('update:density', DEFAULT_TABLE_DENSITY)
}

function toggleColumn(key) {
  const keys = props.visibleKeys.includes(key)
    ? props.visibleKeys.filter(item => item !== key)
    : [...props.visibleKeys, key]
  if (configurableColumns.value.some(column => keys.includes(column.key))) emit('update:visibleKeys', [...new Set(keys)])
}
</script>

<style scoped>
.table-tools {
  display: flex;
  align-items: center;
  gap: 2px;
}

.tools-panel {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.tools-panel-title {
  margin-bottom: 4px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.tools-density-group {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.tools-reset {
  margin-top: 8px;
}
</style>
