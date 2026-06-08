<template>
  <div class="db-timeline-wrapper">
    <div class="db-timeline" ref="trackRef">
      <!-- 横线轨道 -->
      <div class="db-timeline__track"></div>

      <!-- 节点列表 -->
      <div
        v-for="group in groups"
        :key="group.date"
        class="db-timeline__node-wrap"
        @click="$emit('node-click', group.date)"
      >
        <!-- 日期标签 -->
        <div class="db-timeline__date" :style="{ color: nodeColor(group) }">
          {{ group.date }}
        </div>

        <!-- 圆形节点 -->
        <div class="db-timeline__node" :style="{ background: nodeColor(group), borderColor: nodeColor(group) }">
          <span class="db-timeline__node-count">{{ group.product_count || 0 }}</span>
          <!-- 加急红点 -->
          <span v-if="group.has_urgent" class="db-timeline__urgent-dot"></span>
        </div>

        <!-- 型号列表 -->
        <div class="db-timeline__models">
          <span
            v-for="model in (group.models || []).slice(0, 3)"
            :key="model"
            class="db-timeline__model-tag"
          >{{ model }}</span>
          <span v-if="(group.models || []).length > 3" class="db-timeline__model-more">
            +{{ group.models.length - 3 }}
          </span>
        </div>

        <!-- 剩余量 -->
        <div class="db-timeline__remaining">
          余 {{ group.remaining_qty ?? '—' }}
        </div>
      </div>
    </div>

    <div v-if="!groups || groups.length === 0" class="db-timeline__empty">
      暂无交货计划
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  groups: { type: Array, default: () => [] },
})

defineEmits(['node-click'])

const trackRef = ref(null)

function daysLeft(dateStr) {
  if (!dateStr) return null
  const target = new Date(dateStr)
  const now    = new Date()
  now.setHours(0, 0, 0, 0)
  return Math.round((target - now) / (1000 * 60 * 60 * 24))
}

function nodeColor(group) {
  if (group.has_urgent) return 'var(--db-accent-red)'
  const days = daysLeft(group.date)
  if (days != null && days <= 3) return 'var(--db-accent-orange)'
  return 'var(--db-accent-blue)'
}
</script>

<style scoped>
.db-timeline-wrapper {
  overflow-x: auto;
  padding-bottom: 8px;
}

.db-timeline-wrapper::-webkit-scrollbar {
  height: 4px;
}
.db-timeline-wrapper::-webkit-scrollbar-track {
  background: transparent;
}
.db-timeline-wrapper::-webkit-scrollbar-thumb {
  background: var(--db-scrollbar);
  border-radius: 2px;
}

.db-timeline {
  display: inline-flex;
  align-items: flex-start;
  position: relative;
  padding: 40px 24px 16px;
  min-width: max-content;
  gap: 0;
}

/* 横线轨道 */
.db-timeline__track {
  position: absolute;
  top: 74px;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--db-border);
  z-index: 0;
}

/* 节点容器 */
.db-timeline__node-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  min-width: 110px;
  cursor: pointer;
  z-index: 1;
  padding: 0 12px;
  transition: transform 0.18s;
}

.db-timeline__node-wrap:hover {
  transform: translateY(-3px);
}

/* 日期标签 */
.db-timeline__date {
  font-size: 12px;
  font-weight: 600;
  font-family: 'SF Mono', monospace;
  white-space: nowrap;
}

/* 圆形节点 */
.db-timeline__node {
  position: relative;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 2px solid;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  box-shadow: 0 2px 8px var(--db-shadow);
}

.db-timeline__node-count {
  font-size: 13px;
  font-weight: 700;
  color: #fff;
}

/* 加急红点 */
.db-timeline__urgent-dot {
  position: absolute;
  top: -3px;
  right: -3px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: var(--db-accent-red);
  border: 2px solid var(--db-card-bg);
}

/* 型号 tags */
.db-timeline__models {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 3px;
  max-width: 110px;
}

.db-timeline__model-tag {
  font-size: 10px;
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--db-badge-blue-bg);
  color: var(--db-accent-blue);
  white-space: nowrap;
}

.db-timeline__model-more {
  font-size: 10px;
  color: var(--db-text-muted);
}

/* 剩余量 */
.db-timeline__remaining {
  font-size: 11px;
  color: var(--db-text-muted);
  white-space: nowrap;
}

.db-timeline__empty {
  text-align: center;
  padding: 32px 0;
  color: var(--db-text-muted);
  font-size: 13px;
}
</style>
