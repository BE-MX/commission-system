<template>
  <section class="brief lg-card is-static" aria-label="今日简报">
    <div class="brief__meta">
      <h3><span class="brief__badge">{{ brief?.source === 'ai' ? 'AI' : '规则' }}</span>今日简报</h3>
      <p v-if="brief">{{ brief.brief_date.slice(5).replace('-', '/') }} · {{ brief.pushed_at ? '已推送钉钉' : '未推送' }}</p>
      <p v-else-if="loading">正在生成…</p>
      <p v-else>简报暂不可用，稍后刷新</p>
    </div>
    <ol v-if="brief?.top?.length" class="brief__list">
      <li v-for="(item, i) in brief.top" :key="item.id">
        <button type="button" @click="emit('open', item.id)">
          <span class="brief__n">{{ i + 1 }}</span>
          <span class="brief__body">
            <span class="brief__title"><span class="task-code">{{ item.code }}</span> {{ item.title }}</span>
            <span class="brief__why">{{ item.reason }}</span>
          </span>
        </button>
      </li>
    </ol>
    <p v-else-if="brief" class="brief__empty">没有未结束的任务，今天可以专注新想法。</p>
    <div v-if="brief" class="brief__counts">
      <div><b>{{ brief.pending_confirm }}</b><span>待确认</span></div>
      <div :class="{ 'is-alert': brief.overdue }"><b>{{ brief.overdue }}</b><span>逾期</span></div>
      <div :class="{ 'is-alert': brief.blocked }"><b>{{ brief.blocked }}</b><span>受阻</span></div>
    </div>
  </section>
</template>

<script setup>
defineProps({
  brief: { type: Object, default: null },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['open'])
</script>

<style scoped>
.brief { display: grid; grid-template-columns: 200px 1fr auto; gap: 20px; align-items: start; padding: 16px 20px; }
.brief__meta h3 { display: flex; align-items: center; gap: 8px; margin: 0; font: 700 15px var(--font-display); }
.brief__meta p { margin: 6px 0 0; font-size: 12px; color: var(--text-muted); }
.brief__badge { padding: 2px 6px; border-radius: 6px; font: 700 11px var(--font-display); color: var(--card-bg); background: var(--sidebar-glass-from); }
.brief__list { display: grid; gap: 8px; margin: 0; padding: 0; list-style: none; }
.brief__list button {
  display: grid; grid-template-columns: 20px 1fr; gap: 10px; width: 100%; padding: 9px 12px;
  border: 0; border-radius: 12px; background: color-mix(in srgb, var(--card-bg) 55%, transparent); text-align: left; cursor: pointer;
  transition: background-color 150ms ease, transform 160ms cubic-bezier(0.23, 1, 0.32, 1);
}
.brief__list button:hover { background: color-mix(in srgb, var(--card-bg) 90%, transparent); }
.brief__list button:active { transform: scale(0.99); }
.brief__n { font: 800 15px var(--font-display); color: var(--color-primary); }
.brief__body { display: grid; gap: 2px; }
.brief__title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.brief__why { font-size: 12px; color: var(--text-secondary); }
.brief__empty { margin: 0; font-size: 13px; color: var(--text-secondary); }
.brief__counts { display: flex; gap: 8px; }
.brief__counts div { min-width: 64px; padding: 10px 12px; border-radius: 12px; background: var(--color-gold-soft); text-align: center; }
.brief__counts b { display: block; font: 800 20px var(--font-display); color: var(--color-warning-text); font-variant-numeric: tabular-nums; }
.brief__counts span { font-size: 11.5px; color: var(--color-warning-text); }
.brief__counts .is-alert { background: var(--color-danger-bg); }
.brief__counts .is-alert b, .brief__counts .is-alert span { color: var(--color-danger-text); }
@media (max-width: 960px) { .brief { grid-template-columns: 1fr; } }
</style>
