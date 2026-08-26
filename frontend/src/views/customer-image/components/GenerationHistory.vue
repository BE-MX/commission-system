<script setup>
import { formatBeijingShortDateTime } from '@/utils/datetime'
import { useCustomerImageI18n } from '../i18n.js'

defineProps({
  generations: { type: Array, default: () => [] },
  generationUrls: { type: Object, default: () => ({}) },
  selectedId: { type: [Number, String], default: null },
})

defineEmits(['select'])
const { t } = useCustomerImageI18n()

function statusLabel(status) {
  return t(`history.status.${['queued', 'running', 'succeeded', 'failed'].includes(status) ? status : 'processing'}`)
}

function dateLabel(value) {
  return formatBeijingShortDateTime(value)
}
</script>

<template>
  <section class="generation-history" aria-labelledby="history-title">
    <div class="history-heading">
      <h2 id="history-title">{{ t('history.title') }}</h2>
      <span>{{ generations.length }}</span>
    </div>
    <p v-if="!generations.length" class="empty">{{ t('history.empty') }}</p>
    <div v-else class="history-list">
      <button
        v-for="generation in generations"
        :key="generation.id"
        type="button"
        class="generation-row"
        :class="{ selected: generation.id === selectedId }"
        @click="$emit('select', generation)"
      >
        <span class="thumb">
          <img v-if="generationUrls[generation.id]" :src="generationUrls[generation.id]" alt="">
          <span v-else class="status-mark" :data-status="generation.status" aria-hidden="true" />
        </span>
        <span class="generation-copy">
          <strong>{{ generation.product_name }}</strong>
          <small>{{ dateLabel(generation.created_at) }}</small>
        </span>
        <span class="status" :data-status="generation.status">{{ statusLabel(generation.status) }}</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.generation-history { display: grid; gap: 12px; align-content: start; }
.history-heading { display: flex; min-height: 44px; align-items: center; justify-content: space-between; }
h2 { margin: 0; color: var(--cip-ink); font-family: var(--cip-font-display); font-size: 16px; font-weight: 500; }
.history-heading > span { color: var(--cip-faint); font-size: 11px; }
.empty { margin: 0; color: var(--cip-muted); font-size: 12px; line-height: 1.65; }
.history-list { display: grid; gap: 7px; }
.generation-row { display: grid; min-height: 60px; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 10px; width: 100%; padding: 7px; cursor: pointer; border: 1px solid transparent; border-radius: 12px; color: var(--cip-ink); background: transparent; text-align: left; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.generation-row.selected { border-color: var(--cip-border-strong); background: var(--cip-surface-subtle); }
.generation-row:active { transform: scale(.98); }
.thumb { display: grid; width: 44px; height: 44px; place-items: center; overflow: hidden; border-radius: 9px; background: var(--cip-accent-soft); }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.status-mark { width: 8px; height: 8px; border-radius: 50%; background: var(--cip-faint); }
.status-mark[data-status="running"], .status-mark[data-status="queued"] { background: var(--cip-highlight); }
.status-mark[data-status="succeeded"] { background: var(--cip-sand); }
.status-mark[data-status="failed"] { background: var(--cip-danger); }
.generation-copy { min-width: 0; }
.generation-copy strong, .generation-copy small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.generation-copy strong { font-size: 12px; }
.generation-copy small { margin-top: 3px; color: var(--cip-muted); font-size: 10px; }
.status { color: var(--cip-muted); font-size: 10px; }
.status[data-status="succeeded"] { color: var(--cip-success); }
.status[data-status="failed"] { color: var(--cip-danger); }
@media (hover: hover) and (pointer: fine) { .generation-row:hover { background: var(--cip-surface-subtle); } }
@media (prefers-reduced-motion: reduce) { .generation-row { transition: none; } .generation-row:active { transform: none; } }
</style>
