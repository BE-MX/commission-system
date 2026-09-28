<template>
  <section class="weekly-highs" aria-label="近四周每周最高汇率">
    <div class="weekly-heading">
      <h4>近四周每周最高汇率</h4>
      <span v-if="summary">最近完整周至 {{ summary.weeks.at(-1).end }} · FRED 更新至 {{ summary.latestDate }}</span>
    </div>
    <div v-show="summary" ref="chartElement" class="weekly-chart" role="img" :aria-label="chartDescription" />
    <p v-if="!summary" class="weekly-note">日度历史暂不可用，无法比较每周最高汇率。</p>
    <p v-else-if="latestWeek && !latestWeek.high" class="weekly-note weekly-note--missing">{{ latestWeek.start }} 至 {{ latestWeek.end }} 尚无 FRED 已公布观测值，暂不能计算这一周的最高汇率；中国银行买入价不参与这张图。</p>
    <p v-else class="weekly-note">按周一至周日分组，仅比较 FRED 已公布日度汇率；中国银行当前买入价不参与。空白周表示暂无观测值。</p>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { buildWeeklyHighs } from './weeklyHighs'

echarts.use([BarChart, GridComponent, TooltipComponent, CanvasRenderer])
const props = defineProps({ history: Array, today: String })
const summary = computed(() => buildWeeklyHighs(props.history, props.today))
const latestWeek = computed(() => summary.value?.weeks.at(-1))
const chartDescription = computed(() => summary.value?.weeks.map(week =>
  `${week.start} 至 ${week.end}：${week.high ? `${week.high.weekdays.join('、')}最高，${week.high.rate.toFixed(4)}人民币每美元` : '暂无观测值'}`,
).join('；') || '暂无可用历史数据')
const chartElement = ref(null)
let chart, observer

async function renderChart() {
  await nextTick()
  if (!chartElement.value || !summary.value) return
  chart ||= echarts.init(chartElement.value)
  const style = getComputedStyle(chartElement.value)
  const color = name => style.getPropertyValue(name).trim()
  const weeks = summary.value.weeks
  chart.setOption({
    animation: false,
    grid: { left: 45, right: 12, top: 36, bottom: 52 },
    tooltip: { trigger: 'item', confine: true, formatter: ({ dataIndex }) => {
      const week = weeks[dataIndex]
      return week.high
        ? `${week.start} 至 ${week.end}<br/>${week.high.dates.map((date, index) => `${date} ${week.high.weekdays[index]}`).join('、')}：${week.high.rate.toFixed(4)}`
        : `${week.start} 至 ${week.end}<br/>暂无观测值`
    } },
    xAxis: { type: 'category', data: weeks.map(week => week.start), axisTick: { show: false }, axisLine: { lineStyle: { color: color('--border-color') } }, axisLabel: { interval: 0, color: color('--text-secondary'), fontSize: 11, formatter: (_, index) => {
      const week = weeks[index]
      return `${week.start.slice(5)} 起\n${week.high ? week.high.weekdays.join('/') : '无数据'}`
    } } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: color('--text-secondary'), formatter: value => Number(value).toFixed(3) }, splitLine: { lineStyle: { color: color('--border-color') } } },
    series: [{ type: 'bar', data: weeks.map(week => week.high?.rate ?? null), barMaxWidth: 72, itemStyle: { color: color('--color-primary'), borderRadius: [4, 4, 0, 0] }, label: { show: true, position: 'top', color: color('--text-primary'), fontSize: 11, fontWeight: 600, formatter: ({ dataIndex }) => weeks[dataIndex].high?.rate.toFixed(4) || '' } }],
  })
  chart.resize()
}

watch(summary, renderChart)
onMounted(() => {
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(chartElement.value)
  renderChart()
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>

<style scoped>
.weekly-highs { margin-top: 18px; padding-top: 18px; border-top: 1px solid var(--border-color); }
.weekly-heading { display: flex; align-items: baseline; justify-content: space-between; flex-wrap: wrap; gap: 4px 12px; }
.weekly-heading h4 { margin: 0; font-size: 15px; }
.weekly-heading span, .weekly-note { color: var(--text-secondary); font-size: 12px; }
.weekly-chart { height: 220px; width: 100%; }
.weekly-note { margin: 2px 0 0; line-height: 1.6; }
.weekly-note--missing { color: var(--color-warning-text); }
@media(max-width:650px) { .weekly-chart { height: 205px; } }
</style>
