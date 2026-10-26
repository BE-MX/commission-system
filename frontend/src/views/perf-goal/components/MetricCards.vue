<template>
  <div class="pg-metric-cards">
    <div v-for="m in METRICS" :key="m.key" class="pg-mcard">
      <div class="pg-m-name">{{ m.name }} <span class="pg-m-tag">{{ m.unit }} · {{ periodLabel }}</span></div>
      <div class="pg-m-rate">
        <span v-if="rateOf(m.key) == null" style="font-size:20px;color:var(--pg-faint)">未设目标</span>
        <template v-else>{{ rateOf(m.key).toFixed(1) }}<small>%</small></template>
      </div>
      <div class="pg-m-nums">
        <span>已完成 <b>{{ fmtMetric(m.key, cell(m.key)?.achieved) }}</b></span>
        <span>目标 <b>{{ cell(m.key)?.target ? fmtMetric(m.key, cell(m.key).target) : '—' }}</b></span>
      </div>
      <div class="pg-m-progress">
        <div class="pg-fill" :class="{ 'pg-over': (rateOf(m.key) ?? 0) >= 100 }" :style="{ width: `${fillWidth(m.key)}%` }"></div>
        <div class="pg-tp-mark" :style="{ left: `${Math.min(timeProgress ?? 0, 100)}%` }" :data-tp="`${timeProgress ?? '—'}%`"></div>
      </div>
      <div class="pg-m-foot">
        <span v-if="deltaOf(m.key) == null" class="pg-delta" style="color:var(--pg-faint)">—</span>
        <span v-else class="pg-delta" :class="deltaOf(m.key) >= 0 ? 'pg-up' : 'pg-down'">
          {{ deltaOf(m.key) >= 0 ? '超前' : '落后' }} {{ fmtPp(deltaOf(m.key)) }}
        </span>
        <span class="pg-mom">{{ momText(m.key) }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { METRICS, fmtMetric, fmtPp, round2 } from '../helpers'

const props = defineProps({
  metrics: { type: Object, default: () => ({}) },
  timeProgress: { type: Number, default: null },
  periodLabel: { type: String, default: '' },
  momLabel: { type: String, default: '较上期' },
})
const cell = key => props.metrics?.[key] || null
const rateOf = key => cell(key)?.rate ?? null
const deltaOf = key => cell(key)?.delta_pp ?? null
const fillWidth = key => Math.min(rateOf(key) ?? 0, 100)
const momText = key => {
  const c = cell(key)
  if (!c || c.rate == null || c.prev_rate == null) return ''
  return `${props.momLabel} ${fmtPp(round2(c.rate - c.prev_rate))}`
}
</script>
