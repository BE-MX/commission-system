<template>
  <draggable
    v-model="localCards"
    item-key="key"
    tag="div"
    class="dashboard-actions"
    :disabled="!editing"
    :animation="150"
    ghost-class="drag-ghost"
    handle=".dash-drag-handle"
    @end="emitReorder"
  >
    <template #item="{ element: card }">
      <component
        :is="editing ? 'div' : RouterLink"
        :to="editing ? undefined : card.route"
        class="action-card lg-card"
        :class="{ 'dash-card-dimmed': editing && isHiddenFn('actions', card.key) }"
      >
        <div class="action-icon-wrapper" :class="`action-bg-${card.bg}`">
          <el-badge
            v-if="card.badge && card.badge(data) > 0"
            :value="card.badge(data)"
            class="action-badge"
          >
            <el-icon><component :is="card.icon" /></el-icon>
          </el-badge>
          <el-icon v-else><component :is="card.icon" /></el-icon>
        </div>
        <div class="action-info">
          <div class="action-name">{{ card.name }}</div>
          <div class="action-desc">{{ card.desc }}</div>
        </div>
        <el-icon v-if="!editing" class="action-arrow"><ArrowRight /></el-icon>

        <!-- 编辑态控件 -->
        <template v-if="editing">
          <span class="dash-drag-handle" title="拖拽排序">
            <el-icon><Rank /></el-icon>
          </span>
          <button
            class="dash-eye-btn"
            :title="isHiddenFn('actions', card.key) ? '显示此卡片' : '隐藏此卡片'"
            @click.stop="$emit('toggle', card.key)"
          >
            <el-icon><View v-if="!isHiddenFn('actions', card.key)" /><Hide v-else /></el-icon>
          </button>
        </template>
      </component>
    </template>
  </draggable>
</template>

<script setup>
import { ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import draggable from 'vuedraggable'
import { ArrowRight, Hide, Rank, View } from '@element-plus/icons-vue'

const props = defineProps({
  data: { type: Object, required: true },
  cards: { type: Array, required: true },
  editing: { type: Boolean, default: false },
  isHiddenFn: { type: Function, required: true },
})

const emit = defineEmits(['reorder', 'toggle'])

const localCards = ref([])
watch(() => props.cards, v => { localCards.value = [...v] }, { immediate: true })

function emitReorder() {
  emit('reorder', localCards.value.map(c => c.key))
}
</script>

<style scoped>
.dashboard-actions {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 12px;
}

.action-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
  cursor: pointer;
  text-decoration: none;
}
@media (hover: hover) and (pointer: fine) {
  .action-card:hover .action-arrow {
    opacity: 1;
    transform: translateX(2px);
  }
}

.action-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 10px;
  flex-shrink: 0;
  color: #fff;
  /* 顶部内高光 + 投影：给图标块一点厚度，贴合玻璃主题 */
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.22), 0 2px 6px rgba(26, 24, 22, 0.14);
}

.action-bg-gold {
  background: linear-gradient(135deg, var(--color-gold), var(--color-primary));
}
.action-bg-dark {
  /* 暖墨渐变（原蓝灰 text-secondary→ink-dark 与暖金品牌色打架，2026-07-25 修正） */
  background: linear-gradient(135deg, var(--dash-icon-dark-from), var(--dash-icon-dark-to));
}

.action-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}

.action-name {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.action-desc {
  font-family: var(--font-body);
  font-size: 12px;
  color: var(--text-muted);
}

.action-arrow {
  color: var(--text-muted);
  opacity: 0;
  transition: opacity 200ms var(--ease-out-strong), transform 200ms var(--ease-out-strong);
  flex-shrink: 0;
}

/* Badge 覆盖 */
.action-card :deep(.el-badge__content) {
  border: none;
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 600;
}
.action-card :deep(.el-badge__content.is-fixed) {
  top: 4px;
  right: 4px;
}

@media (max-width: 767px) {
  .dashboard-actions {
    grid-template-columns: 1fr;
  }
}
</style>
