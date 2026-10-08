<template><div><div v-if="rows.length" ref="host" class="decision-chart" role="img" :aria-label="`${title}，下方可展开表格查看数据`" /><el-empty v-else :description="'暂无可绘制的数据'" :image-size="64" /><p v-if="chartError" role="status" class="decision-warning">图形暂不可用，已保留下方完整数据表。</p><div v-if="rows.length" class="chart-controls"><GlassButton variant="link" :disabled="chartError" @click="exportPng">导出图表 PNG</GlassButton></div><details v-if="rows.length" class="chart-alternative" :open="chartError"><summary>查看 {{ title }} 数据表（支持键盘）</summary><DecisionTable :rows="rows" :columns="columns" :caption="title" action="查看证据" @open="$emit('select', $event)" /></details></div></template>
<script setup>
import { inject, onBeforeUnmount, onMounted, ref, watch, nextTick } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, BarChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, VisualMapComponent, AriaComponent, TitleComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import DecisionTable from './DecisionTable.vue'
import GlassButton from '@/components/GlassButton.vue'
import { msgWarning } from '@/utils/feedback'
echarts.use([LineChart, BarChart, HeatmapChart, GridComponent, TooltipComponent, VisualMapComponent, AriaComponent, TitleComponent, CanvasRenderer])
const props = defineProps({ title: String, rows: { type: Array, default: () => [] }, type: { type: String, default: 'line' }, x: { type: String, default: 'date' }, value: { type: String, default: 'amount' }, columns: { type: Array, default: () => [] }, snapshot: Object })
const emit = defineEmits(['select']), host = ref(null), chartError = ref(false)
const meta = inject('decisionMeta', null)
let chart, resizeObserver
const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
function token(key) { return getComputedStyle(document.documentElement).getPropertyValue(key).trim() }
function exportPng() {
  if (!chart) return
  const exportHost = document.createElement('div')
  exportHost.style.width = '1200px'; exportHost.style.height = '640px'; exportHost.style.position = 'fixed'; exportHost.style.left = '-10000px'
  document.body.appendChild(exportHost)
  let exportChart
  try {
    exportChart = echarts.init(exportHost)
    const snapshot = props.snapshot || meta?.value, period = snapshot?.period, scope = snapshot?.scope_summary?.mode === 'all' ? '全量权限下所选客户' : '本人权限下所选客户'
    const note = period ? `${period.start_date} — ${period.end_date} · ${scope}（${snapshot.scope_summary.customer_count}位）· 北京时间\n本公司成交需求样本 · 当前状态重算 · 指标 ${snapshot.metric_version} · 规则 ${snapshot.rule_version}` : '授权范围内当前状态重算；以页面口径为准'
    exportChart.setOption({ ...chart.getOption(), animation: false, title: { text: props.title, subtext: note, left: 25, top: 18, textStyle: { color: token('--text-primary'), fontSize: 18 }, subtextStyle: { color: token('--text-secondary'), fontSize: 12, lineHeight: 20 } }, grid: { top: 118, bottom: props.type === 'heatmap' ? 80 : 65, left: 85, right: 45 } })
    const link = document.createElement('a'); link.href = exportChart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: token('--button-surface') }); link.download = `${props.title.replace(/[\\/:*?"<>|]/g, '-')}-${period?.end_date || 'analysis'}.png`; link.click()
  } catch (cause) { msgWarning(`图表导出失败：${cause.message}`) }
  finally { exportChart?.dispose(); exportHost.remove() }
}
async function draw() {
  await nextTick()
  if (!host.value || !props.rows.length) { chart?.dispose(); chart = null; return }
  chartError.value = false
  try {
  if (!chart) { chart = echarts.init(host.value); chart.on('click', event => { if (props.rows[event.dataIndex]) emit('select', props.rows[event.dataIndex]) }) }
  const gold = token('--button-primary'), ink = token('--text-secondary'), border = token('--border-color')
  const xs = [...new Set(props.rows.map(row => String(row[props.x])))], ys = [...new Set(props.rows.map(row => String(row.y)))]
  const heat = props.type === 'heatmap'
  chart.setOption({ animation: !motion.matches, animationDuration: 180, aria: { enabled: true }, tooltip: { trigger: heat ? 'item' : 'axis', confine: true }, grid: { top: 20, right: 20, bottom: heat ? 65 : 45, left: 65 }, textStyle: { color: ink }, xAxis: { type: 'category', data: xs, axisLine: { lineStyle: { color: border } }, axisLabel: { hideOverlap: true } }, yAxis: { type: heat ? 'category' : 'value', ...(heat ? { data: ys } : {}), splitLine: { lineStyle: { color: border } } }, ...(heat ? { visualMap: { min: 0, max: Math.max(1, ...props.rows.map(row => Number(row.value) || 0)), orient: 'horizontal', left: 'center', bottom: 0, inRange: { color: [token('--tag-gold-bg'), gold] } } } : {}), series: [{ type: heat ? 'heatmap' : props.type, data: props.rows.map(row => heat ? [xs.indexOf(String(row[props.x])), ys.indexOf(String(row.y)), row.value] : row[props.value] == null ? null : Number(row[props.value])), connectNulls: false, smooth: false, showSymbol: props.rows.length < 35, itemStyle: { color: gold }, lineStyle: { width: 2.5 }, ...(heat ? { label: { show: true, color: token('--text-primary') } } : {}) }] }, true)
  chart.resize()
  resizeObserver?.observe(host.value)
  } catch (cause) { chartError.value = true; console.warn('Decision chart unavailable:', cause.message) }
}
onMounted(() => { draw(); resizeObserver = new ResizeObserver(() => chart?.resize()); if (host.value) resizeObserver.observe(host.value); motion.addEventListener('change', draw) })
watch(() => [props.rows, props.type, props.value, props.x], draw, { deep: true })
onBeforeUnmount(() => { resizeObserver?.disconnect(); chart?.dispose(); motion.removeEventListener('change', draw) })
</script>
