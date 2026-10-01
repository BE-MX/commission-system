<template>
  <!-- 表格工具四图标：刷新 → 列显示 → 密度 → 全屏，顺序固定 -->
  <div class="table-tools">
    <el-tooltip content="刷新" placement="top" :show-after="300">
      <GlassButton variant="ghost" :left-icon="Refresh" aria-label="刷新" @click="emit('refresh')" />
    </el-tooltip>

    <el-popover v-if="columns.length" trigger="click" placement="bottom-end" width="200">
      <template #reference>
        <GlassButton variant="ghost" :left-icon="SetUp" aria-label="列显示设置" />
      </template>
      <div class="tools-panel">
        <div class="tools-panel-title">列显示</div>
        <el-checkbox
          v-for="column in columns"
          :key="column.key"
          :model-value="visibleKeys.includes(column.key)"
          :disabled="visibleColumnCount === 1 && visibleKeys.includes(column.key)"
          @change="toggleColumn(column.key)"
        >
          {{ column.label }}
        </el-checkbox>
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
import { computed } from 'vue'

const props = defineProps({
  columns: { type: Array, default: () => [] },
  visibleKeys: { type: Array, default: () => [] },
  density: { type: String, default: 'default' },
  fullscreen: { type: Boolean, default: false },
})
const emit = defineEmits(['refresh', 'fullscreen', 'update:visibleKeys', 'update:density'])
const visibleColumnCount = computed(() => props.columns.filter(column => props.visibleKeys.includes(column.key)).length)

function toggleColumn(key) {
  const keys = props.visibleKeys.includes(key)
    ? props.visibleKeys.filter(item => item !== key)
    : [...props.visibleKeys, key]
  if (props.columns.some(column => keys.includes(column.key))) emit('update:visibleKeys', keys)
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
</style>
