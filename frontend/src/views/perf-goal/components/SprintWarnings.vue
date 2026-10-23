<template>
  <div class="pg-card pg-hint-card" style="margin-bottom:0">
    <h3>冲刺提示</h3>
    <div class="pg-hint-sub">{{ subtitle }}</div>
    <div class="pg-hint-list">
      <div v-if="!warnings.length" class="pg-hint-item pg-ok"><b>✓</b> 当前范围各指标按现有速率均可如期完成，无需冲刺。</div>
      <div v-for="(w, i) in warnings" :key="`${w.user_id}-${w.metric}-${i}`" class="pg-hint-item" v-html="formatWarning(w)"></div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { metricMeta, fmtMetric, fmtRate } from '../helpers'

const props = defineProps({
  warnings: { type: Array, default: () => [] },
  timeProgress: { type: Number, default: null },
  remainDays: { type: Number, default: null },
})
const subtitle = computed(() =>
  props.remainDays != null ? `按当前日均速率外推至期末（剩余约 ${props.remainDays} 天）` : '按当前日均速率外推至期末')
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
function formatWarning(w) {
  if (w.text) return `<span class="pg-h-name">${esc(w.name)}</span> · ${esc(w.text)}`
  const meta = metricMeta(w.metric)
  const gap = fmtMetric(w.metric, w.gap, { withUnit: !meta.money })
  const daily = props.remainDays ? fmtMetric(w.metric, w.gap / props.remainDays, { withUnit: !meta.money }) : null
  return `<span class="pg-h-name">${esc(w.name)}</span> · ${meta.name} 缺口 <b>${gap}</b>，按当前速率预计期末完成 <b>${fmtRate(w.projected_rate)}</b><br>` +
    `<span style="color:var(--pg-faint)">${props.timeProgress != null ? `时间进度 ${props.timeProgress}%` : ''}${daily ? ` · 剩余 ${props.remainDays} 天需日均 ${daily}` : ''}</span>`
}
</script>
