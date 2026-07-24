<template>
  <draggable
    v-model="localCards"
    item-key="key"
    tag="div"
    class="dashboard-metrics"
    :class="{ 'is-editing': editing }"
    :disabled="!editing"
    :animation="150"
    ghost-class="drag-ghost"
    handle=".dash-drag-handle"
    @end="emitReorder"
  >
    <template #item="{ element: card }">
      <div
        class="metric-card dash-glass-card"
        :class="{
          'metric-highlight': !editing && card.highlight?.(data),
          'dash-card-dimmed': editing && isHiddenFn('metrics', card.key),
        }"
      >
        <div class="metric-header">
          <span class="metric-label">{{ card.label }}</span>
          <span class="metric-dot" :class="`dot-${card.dot}`" />
        </div>
        <div class="metric-value">{{ card.value(data) }}</div>
        <div class="metric-footer">
          <template v-if="footerOf(card).kind === 'pill'">
            <span class="metric-tag tag-pending">{{ footerOf(card).text }}</span>
          </template>
          <template v-else-if="footerOf(card).kind === 'tag'">
            <el-tag :type="footerOf(card).elType" size="small" effect="plain">
              {{ footerOf(card).text }}
            </el-tag>
          </template>
          <template v-else>
            <span class="metric-status">{{ footerOf(card).text }}</span>
          </template>
        </div>

        <!-- 编辑态控件 -->
        <template v-if="editing">
          <span class="dash-drag-handle" title="拖拽排序">
            <el-icon><Rank /></el-icon>
          </span>
          <button
            class="dash-eye-btn"
            :title="isHiddenFn('metrics', card.key) ? '显示此卡片' : '隐藏此卡片'"
            @click.stop="$emit('toggle', card.key)"
          >
            <el-icon><View v-if="!isHiddenFn('metrics', card.key)" /><Hide v-else /></el-icon>
          </button>
        </template>
      </div>
    </template>
  </draggable>
</template>

<script setup>
import { ref, watch } from 'vue'
import draggable from 'vuedraggable'
import { Hide, Rank, View } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, required: true },
  cards: { type: Array, required: true },     // 已按权限+配置排列
  editing: { type: Boolean, default: false },
  isHiddenFn: { type: Function, required: true },
})

const emit = defineEmits(['reorder', 'toggle'])

const localCards = ref([])
watch(() => props.cards, v => { localCards.value = [...v] }, { immediate: true })

function emitReorder() {
  emit('reorder', localCards.value.map(c => c.key))
}

function footerOf(card) {
  return card.footer?.(props.data) || { kind: 'status', text: '' }
}
</script>

<style scoped>
.dashboard-metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 16px;
}
/* 编辑态改 auto-fill：卡片被拖走时格子不重排跳动 */
.dashboard-metrics.is-editing {
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
}

.metric-card {
  position: relative;
  padding: 20px 22px;
}
.metric-card.metric-highlight {
  border-left: 3px solid var(--color-gold);
}

.metric-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.metric-label {
  font-family: var(--font-display);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  color: var(--text-secondary);
}

.metric-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}
.dot-gold   { background: var(--color-gold); box-shadow: 0 0 6px rgba(245,203,92,0.4); }
.dot-amber  { background: var(--el-warning); box-shadow: 0 0 6px rgba(245,166,35,0.4); }
.dot-green  { background: var(--color-success); box-shadow: 0 0 6px rgba(45,159,111,0.4); }
.dot-blue   { background: var(--color-primary); box-shadow: 0 0 6px rgba(212,148,28,0.4); }
.dot-cyan   { background: var(--color-blue); box-shadow: 0 0 6px rgba(59,130,246,0.4); }
.dot-gray   { background: var(--text-secondary); box-shadow: 0 0 6px rgba(107,114,128,0.3); }

.metric-value {
  font-family: var(--font-display);
  font-size: 30px;
  font-weight: 800;
  color: var(--text-primary);
  line-height: 1.2;
  margin-bottom: 10px;
}

.metric-footer {
  min-height: 22px;
}

.metric-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 10px;
  border-radius: 100px;
  font-family: var(--font-body);
  font-size: 12px;
  font-weight: 500;
  background: var(--color-warning-bg);
  color: var(--color-warning-text);
}

.metric-status {
  font-family: var(--font-body);
  font-size: 12px;
  color: var(--text-muted);
}

@media (max-width: 767px) {
  .dashboard-metrics {
    grid-template-columns: repeat(2, 1fr);
    gap: 12px;
  }
  .metric-value {
    font-size: 24px;
  }
}

@media (max-width: 479px) {
  .dashboard-metrics {
    grid-template-columns: 1fr;
  }
}
</style>
