<template>
  <div class="starter-grid" aria-label="快捷开始">
    <button
      v-for="(starter, index) in starters"
      :key="starter.id"
      type="button"
      class="starter-card"
      @click="emit('select', starter.prompt)"
    >
      <span class="starter-index">0{{ index + 1 }}</span>
      <strong>{{ starter.title }}</strong>
      <span>{{ descriptions[starter.id] }}</span>
    </button>
  </div>
</template>

<script setup>
import { STARTERS } from '../state'

defineProps({
  starters: { type: Array, default: () => STARTERS },
})
const emit = defineEmits(['select'])

const descriptions = {
  'customer-needs': '梳理目标、信息缺口与下一步',
  'product-solution': '形成选型、交付与风险建议',
  'marketing-copy': '规划受众、渠道与执行节奏',
  'customer-communication': '起草邮件、话术与跟进问题',
}
</script>

<style scoped>
.starter-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.starter-card {
  display: grid;
  min-height: 116px;
  grid-template-columns: 1fr auto;
  align-content: start;
  gap: 8px 12px;
  padding: 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: 14px;
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-highlight), var(--card-shadow);
  color: var(--text-primary);
  cursor: pointer;
  text-align: left;
  animation: card-in 260ms var(--ease-out-strong) backwards;
  transition:
    transform 200ms var(--ease-out-strong),
    box-shadow 200ms var(--ease-out-strong),
    border-color 200ms var(--ease-out-strong);
}

.starter-card strong {
  font-family: var(--font-display);
  font-size: 14px;
  font-weight: 700;
}

.starter-card > span:last-child {
  grid-column: 1 / -1;
  color: var(--text-secondary);
  font-size: 12px;
  line-height: 1.55;
}

.starter-index {
  grid-column: 2;
  grid-row: 1;
  color: var(--color-primary);
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
}

.starter-card:focus-visible {
  outline: 2px solid var(--color-primary);
  outline-offset: 2px;
}

.starter-card:nth-child(2) { animation-delay: 60ms; }
.starter-card:nth-child(3) { animation-delay: 120ms; }
.starter-card:nth-child(4) { animation-delay: 180ms; }

@keyframes card-in {
  from { opacity: 0; transform: translateY(12px); }
}

.starter-card:active { transform: scale(0.98); }

@media (hover: hover) and (pointer: fine) {
  .starter-card:hover {
    border-color: var(--border-hover);
    box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow-hover);
    transform: translateY(-3px);
  }
}

@media (prefers-reduced-motion: reduce) {
  .starter-card { animation: none; }
  .starter-card:hover,
  .starter-card:active { transform: none; }
}

@media (max-width: 640px) {
  .starter-grid { grid-template-columns: 1fr; }
  .starter-card { min-height: 94px; }
}
</style>
