<template>
  <div class="db-urgent-panel">
    <!-- 上半：柱状图 -->
    <div class="db-urgent-panel__chart">
      <UrgentBarChart :products="products" :echarts-theme="echartsTheme" />
    </div>

    <!-- 下半：紧急列表 -->
    <div class="db-urgent-panel__list">
      <div
        v-for="product in products"
        :key="product.id || product.model"
        class="db-urgent-panel__item"
        @click="$emit('item-click', product)"
      >
        <!-- 加急 badge -->
        <span class="db-urgent-panel__badge">加急</span>

        <!-- 型号 -->
        <span class="db-urgent-panel__model">{{ product.model }}</span>

        <!-- 数量 -->
        <span class="db-urgent-panel__qty">{{ product.order_qty || 0 }} 件</span>

        <!-- 剩余天数 -->
        <span
          class="db-urgent-panel__days"
          :class="daysClass(product)"
        >
          {{ formatDays(product) }}
        </span>
      </div>

      <div v-if="!products || products.length === 0" class="db-urgent-panel__empty">
        暂无加急订单
      </div>
    </div>
  </div>
</template>

<script setup>
import UrgentBarChart from './UrgentBarChart.vue'

defineProps({
  products:     { type: Array,  default: () => [] },
  echartsTheme: { type: String, default: 'dark' },
})

defineEmits(['item-click'])

function daysLeft(product) {
  if (!product.expected_delivery_date) return null
  const target = new Date(product.expected_delivery_date)
  const now = new Date()
  now.setHours(0, 0, 0, 0)
  return Math.round((target - now) / (1000 * 60 * 60 * 24))
}

function daysClass(product) {
  const days = daysLeft(product)
  if (days == null) return ''
  if (days <= 1)  return 'db-urgent-panel__days--red'
  if (days <= 3)  return 'db-urgent-panel__days--orange'
  return 'db-urgent-panel__days--green'
}

function formatDays(product) {
  const days = daysLeft(product)
  if (days == null) return '—'
  if (days < 0) return `逾期 ${Math.abs(days)} 天`
  if (days === 0) return '今日交货'
  return `剩 ${days} 天`
}
</script>

<style scoped>
.db-urgent-panel {
  display: flex;
  flex-direction: column;
  max-height: 500px;
  background: var(--db-card-bg);
  border: 1px solid var(--db-border);
  border-radius: 10px;
  overflow: hidden;
}

/* 图表区 */
.db-urgent-panel__chart {
  height: 180px;
  flex-shrink: 0;
  border-bottom: 1px solid var(--db-border);
}

/* 列表区 */
.db-urgent-panel__list {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.db-urgent-panel__list::-webkit-scrollbar {
  width: 4px;
}
.db-urgent-panel__list::-webkit-scrollbar-track {
  background: transparent;
}
.db-urgent-panel__list::-webkit-scrollbar-thumb {
  background: var(--db-scrollbar);
  border-radius: 2px;
}

.db-urgent-panel__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  cursor: pointer;
  transition: background 0.15s;
}

.db-urgent-panel__item:hover {
  background: var(--db-hover-bg);
}

.db-urgent-panel__badge {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--db-badge-red-bg);
  color: var(--db-accent-red);
  flex-shrink: 0;
  letter-spacing: 0.04em;
}

.db-urgent-panel__model {
  flex: 1;
  font-size: 13px;
  font-weight: 600;
  color: var(--db-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.db-urgent-panel__qty {
  font-size: 12px;
  color: var(--db-text-secondary);
  white-space: nowrap;
}

.db-urgent-panel__days {
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
  min-width: 60px;
  text-align: right;
}

.db-urgent-panel__days--red {
  color: var(--db-accent-red);
}
.db-urgent-panel__days--orange {
  color: var(--db-accent-orange);
}
.db-urgent-panel__days--green {
  color: var(--db-accent-green);
}

.db-urgent-panel__empty {
  text-align: center;
  padding: 24px 0;
  color: var(--db-text-muted);
  font-size: 13px;
}
</style>
