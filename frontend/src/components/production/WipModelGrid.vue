<template>
  <div class="db-wip-grid">
    <div
      v-for="product in products"
      :key="product.id || product.model"
      class="db-wip-grid__card"
      @click="$emit('product-click', product.order_id)"
    >
      <!-- 型号 -->
      <div class="db-wip-grid__model">{{ product.model }}</div>

      <!-- 当前工序 -->
      <div class="db-wip-grid__process">
        <span class="db-wip-grid__process-dot"></span>
        <span class="db-wip-grid__process-name">{{ product.current_process || '待排程' }}</span>
      </div>

      <!-- mini 进度条 -->
      <div class="db-wip-grid__bar-track">
        <div
          class="db-wip-grid__bar-fill"
          :style="{ width: calcPct(product) + '%' }"
        ></div>
      </div>

      <!-- 工序进度文字 -->
      <div class="db-wip-grid__progress-text">
        {{ product.done_steps || 0 }} / {{ product.process_steps || 0 }} 道工序
        <span class="db-wip-grid__pct-badge">{{ calcPct(product) }}%</span>
      </div>
    </div>

    <div v-if="!products || products.length === 0" class="db-wip-grid__empty">
      暂无在制品数据
    </div>
  </div>
</template>

<script setup>
defineProps({
  products: { type: Array, default: () => [] },
})

defineEmits(['product-click'])

function calcPct(product) {
  const total = product.process_steps || 0
  const done  = product.done_steps || 0
  if (!total) return 0
  return Math.min(100, Math.round((done / total) * 100))
}
</script>

<style scoped>
.db-wip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(168px, 1fr));
  gap: 12px;
  padding: 4px 0;
}

.db-wip-grid__card {
  background: var(--db-card-bg);
  border: 1px solid var(--db-border);
  border-radius: 9px;
  padding: 14px 14px 12px;
  cursor: pointer;
  transition: border-color 0.18s, box-shadow 0.18s, transform 0.18s;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.db-wip-grid__card:hover {
  border-color: var(--db-accent-purple);
  box-shadow: 0 0 0 2px var(--db-accent-purple-alpha), 0 4px 16px var(--db-shadow);
  transform: translateY(-2px);
}

.db-wip-grid__model {
  font-size: 13px;
  font-weight: 700;
  color: var(--db-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.db-wip-grid__process {
  display: flex;
  align-items: center;
  gap: 6px;
}

.db-wip-grid__process-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--db-accent-blue);
  flex-shrink: 0;
  animation: db-pulse 2s ease-in-out infinite;
}

@keyframes db-pulse {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.4; }
}

.db-wip-grid__process-name {
  font-size: 11px;
  color: var(--db-text-secondary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 4px mini 进度条 */
.db-wip-grid__bar-track {
  height: 4px;
  background: var(--db-progress-track);
  border-radius: 2px;
  overflow: hidden;
}

.db-wip-grid__bar-fill {
  height: 100%;
  background: var(--db-accent-purple);
  border-radius: 2px;
  transition: width 0.4s ease;
}

.db-wip-grid__progress-text {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 11px;
  color: var(--db-text-muted);
}

.db-wip-grid__pct-badge {
  font-size: 11px;
  font-weight: 600;
  color: var(--db-accent-purple);
}

.db-wip-grid__empty {
  grid-column: 1 / -1;
  text-align: center;
  padding: 32px 0;
  color: var(--db-text-muted);
  font-size: 13px;
}
</style>
