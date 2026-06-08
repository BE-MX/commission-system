<template>
  <div class="db-kpi-card" @click="$emit('click')" :style="{ '--db-kpi-accent': accentColor }">
    <!-- 顶部颜色条 -->
    <div class="db-kpi-card__accent-bar"></div>

    <div class="db-kpi-card__body">
      <!-- 标签 -->
      <div class="db-kpi-card__label">{{ label }}</div>

      <!-- 主值 -->
      <div class="db-kpi-card__value">{{ value }}</div>

      <!-- 副文本 + trend -->
      <div class="db-kpi-card__footer">
        <span v-if="sub" class="db-kpi-card__sub">{{ sub }}</span>
        <span
          v-if="trend"
          class="db-kpi-card__trend"
          :class="`db-kpi-card__trend--${trendType || 'up'}`"
        >{{ trend }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  label:       { type: String,          default: '' },
  value:       { type: [String, Number], default: '' },
  sub:         { type: String,          default: '' },
  trend:       { type: String,          default: '' },
  trendType:   { type: String,          default: 'up' }, // 'up' | 'warn' | 'hot'
  accentColor: { type: String,          default: 'var(--db-accent-blue)' },
})

defineEmits(['click'])
</script>

<style scoped>
.db-kpi-card {
  position: relative;
  background: var(--db-card-bg);
  border: 1px solid var(--db-border);
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  transition: transform 0.18s, box-shadow 0.18s, border-color 0.18s;
  display: flex;
  flex-direction: column;
}

.db-kpi-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 24px var(--db-shadow);
  border-color: var(--db-kpi-accent, var(--db-accent-blue));
}

/* 顶部颜色条 */
.db-kpi-card__accent-bar {
  height: 3px;
  background: var(--db-kpi-accent, var(--db-accent-blue));
  flex-shrink: 0;
}

.db-kpi-card__body {
  padding: 16px 18px 14px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}

.db-kpi-card__label {
  font-size: 12px;
  color: var(--db-text-muted);
  text-transform: uppercase;
  letter-spacing: 0.06em;
  font-weight: 500;
}

.db-kpi-card__value {
  font-size: 28px;
  font-weight: 700;
  color: var(--db-text-primary);
  line-height: 1.1;
  letter-spacing: -0.01em;
}

.db-kpi-card__footer {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.db-kpi-card__sub {
  font-size: 12px;
  color: var(--db-text-secondary);
}

.db-kpi-card__trend {
  font-size: 11px;
  font-weight: 600;
  padding: 2px 7px;
  border-radius: 10px;
}

.db-kpi-card__trend--up {
  background: var(--db-badge-green-bg);
  color: var(--db-accent-green);
}

.db-kpi-card__trend--warn {
  background: var(--db-badge-orange-bg);
  color: var(--db-accent-orange);
}

.db-kpi-card__trend--hot {
  background: var(--db-badge-red-bg);
  color: var(--db-accent-red);
}
</style>
