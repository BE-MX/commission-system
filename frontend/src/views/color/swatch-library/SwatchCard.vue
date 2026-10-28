<template>
  <button type="button" class="sw" @click="$emit('open')">
    <span class="chip" :style="{ background: chip }">
      <span class="size">{{ sizeLabel }}</span>
    </span>
    <span class="body">
      <span class="code">
        {{ swatch.color_code }}
        <span class="tag" :class="verdictMeta.cls">{{ verdictMeta.label }}</span>
        <span v-if="swatch.promotion_status === 'pending'" class="tag tag-info">审核中</span>
      </span>
      <span class="sub">{{ swatch.display_name || '—' }}</span>
      <span class="stats">
        <span><b>{{ swatch.stats.count }}</b>测量组</span>
        <span><b>{{ fmt(swatch.stats.mean_de) }}</b>组内ΔE</span>
        <span><b :class="{ warn: swatch.verdict === 'warn' }">{{ fmt(swatch.stats.base_de) }}</b>对基准</span>
      </span>
    </span>
  </button>
</template>

<script setup>
import { computed } from 'vue'
import { labToRgb, rgbCss } from '@/services/colorimeter/deltaE.js'
import { fmt } from './swatchFormat.js'

const props = defineProps({ swatch: { type: Object, required: true } })
defineEmits(['open'])


const chip = computed(() => {
  const lab = props.swatch.stats.avg_lab
  return lab ? rgbCss(labToRgb(lab)) : 'var(--button-quiet-hover)'
})
const sizeLabel = computed(() => (props.swatch.size_unit === 'inch'
  ? `${props.swatch.size_value}″` : `${props.swatch.size_value} cm`))
const verdictMeta = computed(() => {
  if (props.swatch.verdict === 'none') return { label: '未测量', cls: 'tag-mute' }
  if (props.swatch.library_scope === 'public') return { label: '标准', cls: 'tag-gold' }
  return props.swatch.verdict === 'warn' ? { label: '偏差', cls: 'tag-warn' } : { label: '符合', cls: 'tag-ok' }
})
</script>

<style scoped>
.sw {
  display: flex; flex-direction: column; padding: 0; text-align: left; cursor: pointer; overflow: hidden;
  border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg);
  transition: transform 200ms cubic-bezier(0.23, 1, 0.32, 1), box-shadow 200ms ease, border-color 160ms ease;
}
.sw:active { transform: scale(0.98); }
.sw:focus-visible { outline: 2px solid var(--button-focus); outline-offset: 2px; }
@media (hover: hover) and (pointer: fine) {
  .sw:hover { transform: translateY(-2px); box-shadow: var(--card-shadow-hover); border-color: var(--border-hover); }
}
.chip { position: relative; display: block; height: 92px; }
.chip::after {
  content: ''; position: absolute; inset: 0;
  background: repeating-linear-gradient(100deg, rgb(255 255 255 / 0.07) 0 2px, transparent 2px 6px),
    linear-gradient(180deg, rgb(255 255 255 / 0.12), rgb(0 0 0 / 0.12));
}
.size {
  position: absolute; right: 10px; top: 10px; z-index: 1; padding: 2px 7px; border-radius: 6px;
  font: 700 11px var(--font-display); background: rgb(20 18 16 / 0.72); color: var(--text-on-dark);
}
.body { display: block; padding: 11px 13px 13px; }
.code { display: flex; align-items: center; gap: 6px; font: 700 15px var(--font-display); color: var(--text-primary); }
.sub { display: block; margin-top: 2px; font-size: 12px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.stats {
  display: flex; justify-content: space-between; margin-top: 10px; padding-top: 10px;
  border-top: 1px dashed var(--border-color); font-size: 12px; color: var(--text-secondary);
}
.stats > span { display: grid; }
.stats > span:last-child { text-align: right; }
.stats b { font: 700 13px var(--font-display); color: var(--text-primary); font-variant-numeric: tabular-nums; }
.stats b.warn { color: var(--button-warning-text); }
.tag { display: inline-flex; align-items: center; height: 20px; padding: 0 7px; border-radius: var(--radius-sm, 6px); font: 600 11px var(--font-display); }
.tag-ok { background: var(--tag-success-bg); color: var(--tag-success-text); }
.tag-warn { background: var(--tag-warning-bg); color: var(--tag-warning-text); }
.tag-gold { background: var(--tag-gold-bg); color: var(--tag-gold-text); }
.tag-info { background: var(--tag-info-bg); color: var(--color-info-text); }
.tag-mute { background: var(--button-quiet-hover); color: var(--text-secondary); }

@media (max-width: 860px) {
  .chip { height: 70px; }
  .stats { font-size: 11px; }
}
</style>
