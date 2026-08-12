<template><div ref="chartEl" class="order-trend-chart" role="img" :aria-label="ariaLabel" /></template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts'

const props = defineProps({
  rows: { type: Array, default: () => [] },
  mode: { type: String, default: 'amount' },
})
const chartEl = ref(null)
let chart
let observer
const ariaLabel = computed(() => ({
  amount: '月度订单金额趋势',
  customers: '月度新签与复购客户趋势',
  orders: '月度下单频次趋势',
}[props.mode] || '月度经营趋势'))

function token(name, fallback) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback
}

function render() {
  if (!chartEl.value) return
  if (!chart) chart = echarts.init(chartEl.value)
  const months = props.rows.map(row => row.month)
  const isAmount = props.mode === 'amount'
  const primary = token('--color-primary', 'goldenrod')
  const success = token('--color-success', 'seagreen')
  const info = token('--color-info-text', 'steelblue')
  const text = token('--text-secondary', 'gray')
  const border = token('--border-color', 'lightgray')
  chart.setOption({
    animationDuration: 350,
    tooltip: { trigger: 'axis' },
    grid: { left: 12, right: 18, top: 28, bottom: 8, containLabel: true },
    legend: { top: 0, right: 0, textStyle: { color: text } },
    xAxis: { type: 'category', data: months, axisLabel: { color: text }, axisLine: { lineStyle: { color: border } } },
    yAxis: { type: 'value', axisLabel: { color: text }, splitLine: { lineStyle: { color: border } } },
    series: isAmount ? [{
      name: 'GMV (USD)', type: 'line', smooth: true, symbolSize: 7,
      data: props.rows.map(row => row.amount_usd),
      lineStyle: { width: 3, color: primary }, itemStyle: { color: primary },
      areaStyle: { color: token('--color-primary-light', 'transparent') },
    }] : (props.mode === 'orders' ? [{
      name: '有效订单数', type: 'line', smooth: true, symbolSize: 7,
      data: props.rows.map(row => row.orders),
      lineStyle: { width: 3, color: info }, itemStyle: { color: info },
      areaStyle: { color: token('--color-info-soft', 'transparent') },
    }] : [
      { name: '新签客户', type: 'bar', data: props.rows.map(row => row.new_sign_customers), itemStyle: { color: info, borderRadius: [5, 5, 0, 0] } },
      { name: '复购客户', type: 'bar', data: props.rows.map(row => row.repeat_customers), itemStyle: { color: success, borderRadius: [5, 5, 0, 0] } },
    ]),
  }, true)
}

watch(() => [props.rows, props.mode], () => nextTick(render), { deep: true })
onMounted(() => {
  render()
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(chartEl.value)
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>

<style scoped>.order-trend-chart { width: 100%; height: 290px; }</style>
