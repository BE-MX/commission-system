<template>
  <svg viewBox="0 0 610 240" preserveAspectRatio="none" role="img" aria-label="近 7 天检验量">
    <defs>
      <linearGradient id="qcBar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--qc-bar-hi)" /><stop offset="1" stop-color="var(--qc-bar-deep)" /></linearGradient>
      <linearGradient id="qcBarToday" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--qc-today)" /><stop offset="1" stop-color="var(--qc-today-deep)" /></linearGradient>
      <linearGradient id="qcArea" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="var(--qc-ok)" stop-opacity=".28" /><stop offset="1" stop-color="var(--qc-ok)" stop-opacity="0" /></linearGradient>
    </defs>
    <g v-for="tick in ticks" :key="tick.v">
      <line :x1="PL" :x2="W - PR" :y1="tick.y" :y2="tick.y" stroke="var(--qc-line)" :stroke-dasharray="tick.v ? '3 5' : ''" />
      <text :x="PL - 8" :y="tick.y + 4" fill="var(--qc-mute)" font-size="12" text-anchor="end" font-family="Bahnschrift">{{ tick.v }}</text>
      <text :x="W - PR + 8" :y="tick.y + 4" fill="var(--qc-mute)" font-size="12" font-family="Bahnschrift">{{ tick.q }}</text>
    </g>
    <g v-for="bar in bars" :key="bar.date">
      <rect :x="bar.x - bar.w / 2" :y="bar.y" :width="bar.w" :height="H - PB - bar.y" rx="5" :fill="bar.today ? 'url(#qcBarToday)' : 'url(#qcBar)'" :opacity="bar.today ? 1 : 0.85" />
      <text :x="bar.x" :y="bar.y - 8" :fill="bar.today ? 'var(--qc-today)' : 'var(--qc-text-2)'" :font-size="bar.today ? 17 : 15" font-weight="600" text-anchor="middle" font-family="Bahnschrift">{{ bar.orders }}</text>
      <text :x="bar.x" :y="H - PB + 20" :fill="bar.today ? 'var(--qc-text)' : 'var(--qc-dim)'" font-size="14" text-anchor="middle" font-family="Bahnschrift, Microsoft YaHei UI">{{ bar.label }}</text>
      <text :x="bar.x" :y="H - PB + 36" fill="var(--qc-mute)" font-size="12" text-anchor="middle" font-family="Microsoft YaHei UI">周{{ bar.week }}</text>
    </g>
    <path v-if="line" :d="`${line} L${bars.at(-1).x} ${H - PB} L${bars[0].x} ${H - PB}Z`" fill="url(#qcArea)" />
    <path v-if="line" :d="line" fill="none" stroke="var(--qc-ok)" stroke-width="3" stroke-linejoin="round" stroke-linecap="round" />
    <circle v-for="bar in bars" :key="`p${bar.date}`" :cx="bar.x" :cy="bar.qy" :r="bar.today ? 6 : 4" fill="var(--qc-bg)" stroke="var(--qc-ok)" stroke-width="2.5" />
  </svg>
</template>

<script setup>
import { computed } from 'vue'
import { weekdayOf } from '../composables/useInspectionBoard'

const props = defineProps({ trend: { type: Array, default: () => [] } })
const W = 610, H = 240, PL = 34, PR = 44, PT = 26, PB = 40

const niceMax = (value, step) => Math.max(step, Math.ceil((value * 1.15) / step) * step)
const maxOrders = computed(() => niceMax(Math.max(0, ...props.trend.map(d => d.orders)), 10))
const maxQty = computed(() => niceMax(Math.max(0, ...props.trend.map(d => Number(d.qty) || 0)), 1000))
const y = (value, max) => PT + (H - PT - PB) * (1 - value / max)
const kilo = v => (v >= 1000 ? `${(v / 1000).toFixed(1)}k` : String(Math.round(v)))

const ticks = computed(() => [0, 0.25, 0.5, 0.75, 1].map(f => ({
  v: Math.round(maxOrders.value * f), y: y(maxOrders.value * f, maxOrders.value), q: f ? kilo(maxQty.value * f) : '0',
})))

const bars = computed(() => {
  const cw = (W - PL - PR) / Math.max(1, props.trend.length)
  return props.trend.map((d, i) => {
    const today = i === props.trend.length - 1
    const [, m, day] = d.date.split('-')
    return {
      date: d.date, orders: d.orders, today, week: weekdayOf(d.date),
      label: today ? '今天' : `${m}/${day}`,
      x: PL + cw * i + cw / 2, w: cw * 0.46,
      y: y(d.orders, maxOrders.value), qy: y(Number(d.qty) || 0, maxQty.value),
    }
  })
})

const line = computed(() => bars.value.map((b, i) => `${i ? 'L' : 'M'}${b.x.toFixed(1)} ${b.qy.toFixed(1)}`).join(' '))
</script>
