<template>
  <div class="pg-bullet-wrap">
    <div v-for="m in METRICS" :key="m.key" class="pg-bullet-item">
      <div class="pg-b-head">
        <span><b>{{ m.name }}</b> {{ fmtMetric(m.key, cell(m.key)?.achieved) }} / {{ cell(m.key)?.target ? fmtMetric(m.key, cell(m.key).target) : '—' }}</span>
        <span>
          {{ rateOf(m.key) == null ? '—' : `${rateOf(m.key).toFixed(1)}%` }}
          <span v-if="deltaOf(m.key) != null" class="pg-delta" :class="deltaOf(m.key) >= 0 ? 'pg-up' : 'pg-down'">{{ fmtPp(deltaOf(m.key)) }}</span>
        </span>
      </div>
      <div :ref="el => setEl(m.key, el)" class="pg-bullet-chart pg-chart"></div>
    </div>
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { METRICS, fmtMetric, fmtPp, chartPalette } from '../helpers'

const props = defineProps({
  metrics: { type: Object, default: () => ({}) },
  timeProgress: { type: Number, default: null },
})
const cell = key => props.metrics?.[key] || null
const rateOf = key => cell(key)?.rate ?? null
const deltaOf = key => cell(key)?.delta_pp ?? null

const els = ref({})
const charts = {}
function setEl(key, el) { if (el) els.value[key] = el }

function render() {
  const tp = props.timeProgress ?? 100
  const C = chartPalette(Object.values(els.value)[0])
  METRICS.forEach(m => {
    const el = els.value[m.key]
    if (!el) return
    if (!charts[m.key]) charts[m.key] = echarts.init(el)
    const c = cell(m.key) || {}
    const target = Number(c.target) || 0
    const done = Number(c.achieved) || 0
    const rate = c.rate ?? null
    const scale = Math.max(target, done) * 1.12 || 1
    const color = rate == null ? C.target : rate >= 100 ? C.green : rate >= tp ? C.primary : rate >= tp - 30 ? C.orange : C.red
    charts[m.key].setOption({
      grid: { left: 2, right: 2, top: 8, bottom: 8 },
      xAxis: { type: 'value', max: scale, show: false },
      yAxis: { type: 'category', data: [''], show: false },
      animationDuration: 400,
      series: [
        { type: 'bar', barWidth: 18, barGap: '-100%', silent: true, data: [scale], itemStyle: { color: 'rgb(241,245,249)', borderRadius: 3 }, tooltip: { show: false } },
        { type: 'bar', barWidth: 18, barGap: '-100%', silent: true, data: [target], itemStyle: { color: 'rgb(219,227,236)', borderRadius: 3 }, tooltip: { show: false } },
        {
          type: 'bar', barWidth: 9, barGap: '-100%', data: [done], itemStyle: { color, borderRadius: 2 },
          markLine: target ? {
            symbol: 'none', silent: true, animation: false,
            data: [{ xAxis: (target * tp) / 100 }],
            lineStyle: { color: C.amber, type: 'dashed', width: 2 },
            label: { show: false },
          } : undefined,
        },
      ],
    }, true)
  })
}

let observer
watch(() => [props.metrics, props.timeProgress], () => nextTick(render), { deep: true })
onMounted(() => {
  render()
  observer = new ResizeObserver(() => Object.values(charts).forEach(c => c.resize()))
  Object.values(els.value).forEach(el => observer.observe(el))
})
onBeforeUnmount(() => { observer?.disconnect(); Object.values(charts).forEach(c => c.dispose()) })
</script>
