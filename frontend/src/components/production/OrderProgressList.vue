<template>
  <div class="db-order-list">
    <div
      v-for="order in orders"
      :key="order.id"
      class="db-order-list__item"
      @click="$emit('order-click', order.order_id)"
    >
      <!-- 订单头 -->
      <div class="db-order-list__header">
        <span class="db-order-list__id">{{ order.order_id }}</span>
        <span v-if="hasUrgent(order)" class="db-order-list__urgent-tag">加急</span>
        <span class="db-order-list__spacer"></span>
        <span class="db-order-list__qty">
          {{ storedQty(order) }}<em>/{{ totalQty(order) }}</em>
        </span>
        <span class="db-order-list__pct" :style="{ color: pctColor(calcPct(order)) }">
          {{ calcPct(order) }}%
        </span>
      </div>

      <!-- 进度条 -->
      <div class="db-order-list__bar-track">
        <div
          class="db-order-list__bar-fill"
          :style="{ width: calcPct(order) + '%', background: pctColor(calcPct(order)) }"
        ></div>
      </div>

      <!-- 底部信息 -->
      <div class="db-order-list__meta">
        <span>产品 {{ productCount(order) }} 款</span>
        <span>·</span>
        <span>最早交货：{{ earliestDate(order) }}</span>
      </div>
    </div>

    <div v-if="!orders || orders.length === 0" class="db-order-list__empty">
      暂无订单数据
    </div>
  </div>
</template>

<script setup>
defineProps({
  orders: { type: Array, default: () => [] },
})

defineEmits(['order-click'])

function hasUrgent(order) {
  return order.products?.some(p => p.is_urgent === 1)
}

function totalQty(order) {
  if (!order.products?.length) return 0
  return order.products.reduce((s, p) => s + (p.order_qty || 0), 0)
}

function storedQty(order) {
  if (!order.products?.length) return 0
  return order.products.reduce((s, p) => s + (p.received_qty || 0), 0)
}

function calcPct(order) {
  const total = totalQty(order)
  if (!total) return 0
  return Math.min(100, Math.round((storedQty(order) / total) * 100))
}

function pctColor(pct) {
  if (pct >= 100) return 'var(--db-accent-green)'
  if (pct > 60)   return 'var(--db-accent-blue)'
  return 'var(--db-accent-orange)'
}

function productCount(order) {
  return order.products?.length || 0
}

function earliestDate(order) {
  if (!order.products?.length) return '—'
  const dates = order.products
    .map(p => p.expected_delivery_date)
    .filter(Boolean)
    .sort()
  return dates[0] || '—'
}
</script>

<style scoped>
.db-order-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 4px 0;
}

.db-order-list__item {
  background: var(--db-card-bg);
  border: 1px solid var(--db-border);
  border-radius: 8px;
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color 0.18s, box-shadow 0.18s;
}

.db-order-list__item:hover {
  border-color: var(--db-accent-blue);
  box-shadow: 0 2px 12px var(--db-shadow);
}

/* 头部行 */
.db-order-list__header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.db-order-list__id {
  font-size: 13px;
  font-weight: 600;
  color: var(--db-text-primary);
  font-family: 'SF Mono', monospace;
}

.db-order-list__urgent-tag {
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 4px;
  background: var(--db-badge-red-bg);
  color: var(--db-accent-red);
  letter-spacing: 0.04em;
}

.db-order-list__spacer {
  flex: 1;
}

.db-order-list__qty {
  font-size: 13px;
  font-weight: 600;
  color: var(--db-text-primary);
}

.db-order-list__qty em {
  font-style: normal;
  color: var(--db-text-muted);
  font-weight: 400;
}

.db-order-list__pct {
  font-size: 13px;
  font-weight: 700;
  min-width: 36px;
  text-align: right;
}

/* 进度条 */
.db-order-list__bar-track {
  height: 6px;
  background: var(--db-progress-track);
  border-radius: 3px;
  overflow: hidden;
  margin-bottom: 8px;
}

.db-order-list__bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}

/* 底部元信息 */
.db-order-list__meta {
  display: flex;
  gap: 6px;
  font-size: 11px;
  color: var(--db-text-muted);
}

.db-order-list__empty {
  text-align: center;
  padding: 32px 0;
  color: var(--db-text-muted);
  font-size: 13px;
}
</style>
