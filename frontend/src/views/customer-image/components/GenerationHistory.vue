<script setup>
defineProps({
  generations: { type: Array, default: () => [] },
  generationUrls: { type: Object, default: () => ({}) },
  selectedId: { type: [Number, String], default: null },
})

defineEmits(['select'])

function statusLabel(status) {
  return { queued: '已提交', running: '生成中', succeeded: '已完成', failed: '未完成' }[status] || '处理中'
}

function dateLabel(value) {
  if (!value) return ''
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
}
</script>

<template>
  <section class="generation-history" aria-labelledby="history-title">
    <div class="history-heading">
      <h2 id="history-title">历史效果图</h2>
      <span>{{ generations.length }}</span>
    </div>
    <p v-if="!generations.length" class="empty">生成结果会保留在这里，邀请有效期内可随时查看。</p>
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
.generation-history { display: grid; gap: 12px; }
.history-heading { display: flex; min-height: 44px; align-items: center; justify-content: space-between; }
h2 { margin: 0; color: var(--cip-ink); font-size: 15px; }
.history-heading > span { color: var(--cip-muted); font-size: 12px; }
.empty { margin: 0; color: var(--cip-muted); font-size: 12px; line-height: 1.6; }
.history-list { display: grid; gap: 7px; }
.generation-row { display: grid; min-height: 60px; grid-template-columns: 44px minmax(0, 1fr) auto; align-items: center; gap: 9px; width: 100%; padding: 7px; cursor: pointer; border: 1px solid transparent; border-radius: 10px; color: var(--cip-ink); background: transparent; text-align: left; transition: transform 180ms cubic-bezier(0.23, 1, 0.32, 1); }
.generation-row.selected { border-color: var(--cip-border-strong); background: var(--cip-surface-subtle); }
.generation-row:active { transform: scale(.98); }
.thumb { display: grid; width: 44px; height: 44px; place-items: center; overflow: hidden; border-radius: 8px; background: var(--cip-surface-subtle); }
.thumb img { width: 100%; height: 100%; object-fit: cover; }
.status-mark { width: 9px; height: 9px; border-radius: 50%; background: var(--cip-muted); }
.status-mark[data-status="running"], .status-mark[data-status="queued"] { background: var(--cip-accent); }
.status-mark[data-status="succeeded"] { background: var(--cip-success); }
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
