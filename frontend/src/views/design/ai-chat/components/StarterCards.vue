<template>
  <div class="starter-grid" aria-label="快捷开始">
    <button
      v-for="(starter, index) in starters"
      :key="starter.id"
      type="button"
      class="starter-card"
      :aria-pressed="selectedId === starter.id"
      :disabled="disabled"
      @click="emit('select', starter)"
    >
      <span class="starter-index">{{ selectedId === starter.id ? '✓ 已选' : `0${index + 1}` }}</span>
      <strong>{{ starter.title }}</strong>
      <span>{{ starter.description }}</span>
    </button>
  </div>
</template>

<script setup>
defineProps({
  starters: { type: Array, default: () => [] },
  selectedId: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['select'])

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

.starter-card[aria-pressed="true"] { border-color: var(--color-primary); background: var(--color-gold-soft); }
.starter-card:disabled { cursor: not-allowed; opacity: .55; }

@media (hover: hover) and (pointer: fine) {
  .starter-card:hover {
    border-color: var(--border-hover);
    box-shadow: var(--dash-glass-highlight), var(--dash-glass-shadow-hover);
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
