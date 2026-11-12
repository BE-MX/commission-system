<template>
  <div class="stats-chart" :class="{ 'stats-chart--compact': compact }">
    <div ref="host" class="stats-chart__canvas" :style="canvasStyle" role="img" :aria-label="ariaLabel" />
    <div v-if="mode === 'heat'" class="stats-legend stats-heat-legend" aria-label="热力图图例">
      <span>少</span><i v-for="level in 5" :key="level" :style="{ background: `var(--stats-heat-${level - 1})` }" /><span>多</span>
      <span>斜纹 / 灰色为周日或非工作日</span>
    </div>
    <div v-else class="stats-legend">
      <span><i />每日跟进次数</span><span><i class="is-line" />7 日移动平均（仅工作日）</span>
      <span v-if="teamAverage !== null && teamAverage !== undefined"><i class="is-dash" />团队人均</span>
    </div>
    <p v-if="chartError" role="status">图形暂不可用，请使用下方数据表。</p>
    <details class="stats-heat-data" :open="chartError">
      <summary>查看每日数据（支持键盘）</summary>
      <table><thead><tr><th>日期</th><th>跟进</th><th>触达</th><th>有效沟通</th><th>明细</th></tr></thead>
        <tbody><tr v-for="day in days" :key="day.date"><td>{{ day.date }} {{ weekday(day.date) }}</td><td>{{ day.count }}</td><td>{{ day.reach }}</td><td>{{ day.effective }}</td>
          <td><button type="button" @click="selectDay(day.date)">查看记录</button></td></tr></tbody></table>
    </details>
  </div>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { BarChart, HeatmapChart, LineChart } from 'echarts/charts'
import { AriaComponent, CalendarComponent, GridComponent, TooltipComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { shortDate, weekday } from './statsModel'

echarts.use([BarChart, HeatmapChart, LineChart, AriaComponent, CalendarComponent, GridComponent, TooltipComponent, VisualMapComponent, CanvasRenderer])
const props = defineProps({
  days: { type: Array, default: () => [] }, people: { type: Array, default: null }, mode: { type: String, default: 'heat' },
  compact: Boolean, teamAverage: [Number, String], today: String,
})
const emit = defineEmits(['select'])
const host = ref(null), chartError = ref(false)
let chart, resizeObserver
const motion = window.matchMedia('(prefers-reduced-motion: reduce)')
const token = name => getComputedStyle(document.documentElement).getPropertyValue(name).trim()
const ariaLabel = computed(() => props.people ? '业务员按日期的跟进热力矩阵' : '每日跟进次数与沟通质量')
const canvasStyle = computed(() => props.people && props.mode === 'heat' ? { height: `${Math.max(210, props.people.length * 42 + 90)}px` } : {})
function selectDay(date, userId) { emit('select', { date, userId }) }
function tooltipDay(value) {
  const [date, count, reach, effective] = value
  return `<strong>${date} ${weekday(date)}</strong><br/>跟进 ${count} 次 · 触达 ${reach} 家 · 有效沟通 ${effective} 次`
}
function heatOption() {
  const colors = [0, 1, 2, 3, 4].map(index => token(`--stats-heat-${index}`))
  const visualMap = { show: false, type: 'piecewise', dimension: props.people ? 2 : 1, pieces: [
    { min: 0, max: 0, color: colors[0] }, { min: 1, max: 2, color: colors[1] },
    { min: 3, max: 4, color: colors[2] }, { min: 5, max: 6, color: colors[3] }, { min: 7, color: colors[4] },
  ] }
  const itemStyle = day => ({
    ...(day.date === props.today ? { borderColor: token('--text-primary'), borderWidth: 2 } : {}),
    ...(!day.workday ? { decal: { symbol: 'rect', color: token('--stats-heat-off'), dashArrayX: [1, 0], dashArrayY: [2, 5], rotation: 0.5 } } : {}),
  })
  if (!props.people) {
    return {
      animation: !motion.matches, animationDuration: 160, aria: { enabled: true, label: { description: `${ariaLabel.value}。逐日数值可展开查看每日数据。` } },
      tooltip: { confine: true, formatter: params => tooltipDay(params.value) },
      visualMap, calendar: {
        left: 12, right: 12, top: 34, bottom: 12, range: [props.days[0]?.date, props.days.at(-1)?.date],
        cellSize: ['auto', props.compact ? 22 : 34], firstDay: 1,
        dayLabel: { nameMap: ['日', '一', '二', '三', '四', '五', '六'], color: token('--text-muted'), fontSize: 11 },
        monthLabel: { color: token('--text-muted'), fontSize: 11 }, yearLabel: { show: false }, splitLine: { show: false },
      },
      series: [{ type: 'heatmap', coordinateSystem: 'calendar', data: props.days.map(day => ({
        value: [day.date, day.count, day.reach, day.effective], itemStyle: itemStyle(day),
      })) }],
    }
  }
  const dates = props.days.map(day => day.date)
  const names = props.people.map(person => person.user.real_name)
  const data = props.people.flatMap((person, y) => person.days.map((day, x) => ({
    value: [x, y, day.count, day.date, day.reach, day.effective], itemStyle: itemStyle(day),
  })))
  return {
    animation: !motion.matches, animationDuration: 160, aria: { enabled: true, label: { description: `${ariaLabel.value}。逐日数值可展开查看每日数据。` } },
    grid: { left: 76, right: 24, top: 20, bottom: 56 }, visualMap,
    tooltip: { confine: true, formatter: params => `${names[params.value[1]]}<br/>${tooltipDay([params.value[3], params.value[2], params.value[4], params.value[5]])}` },
    xAxis: { type: 'category', data: dates, axisLabel: { formatter: shortDate, hideOverlap: true }, splitArea: { show: false } },
    yAxis: { type: 'category', data: names, axisLabel: { color: token('--text-secondary') } },
    series: [{ type: 'heatmap', data, label: { show: false }, itemStyle: { borderColor: token('--button-surface'), borderWidth: 2 } }],
  }
}
function barOption() {
  const days = props.days
  const average = props.teamAverage === null || props.teamAverage === undefined ? null : Number(props.teamAverage)
  return {
    animation: !motion.matches, animationDuration: 160, aria: { enabled: true, label: { description: `${ariaLabel.value}。逐日数值可展开查看每日数据。` } },
    tooltip: { trigger: 'axis', confine: true, formatter: params => {
      const day = days[params[0]?.dataIndex]
      return day ? tooltipDay([day.date, day.count, day.reach, day.effective]) : ''
    } },
    grid: { left: 46, right: 20, top: 24, bottom: 42 },
    xAxis: { type: 'category', data: days.map(day => shortDate(day.date)), axisLabel: { hideOverlap: true }, axisTick: { show: false } },
    yAxis: { type: 'value', min: 0, minInterval: 1, splitLine: { lineStyle: { color: token('--border-color') } } },
    series: [
      { name: '每日跟进次数', type: 'bar', data: days.map(day => ({ value: day.count, itemStyle: {
        color: token(day.workday ? '--stats-series' : '--stats-series-soft'), borderRadius: [4, 4, 0, 0],
      } })), barMaxWidth: 24 },
      { name: '7 日移动平均', type: 'line', data: days.map(day => day.moving_average), connectNulls: false,
        showSymbol: days.length <= 10, symbolSize: 5, lineStyle: { color: token('--stats-line'), width: 2 }, itemStyle: { color: token('--stats-line') } },
      ...(average === null ? [] : [{ name: '团队人均', type: 'line', data: days.map(() => average), showSymbol: false,
        lineStyle: { color: token('--text-muted'), width: 1, type: 'dashed' }, itemStyle: { color: token('--text-muted') }, silent: true }]),
    ],
  }
}
async function draw() {
  await nextTick()
  if (!host.value || !props.days.length) { chart?.dispose(); chart = null; return }
  chartError.value = false
  try {
    if (!chart) {
      chart = echarts.init(host.value)
      chart.on('click', params => {
        if (props.mode === 'bar') return selectDay(props.days[params.dataIndex]?.date)
        if (!props.people) return selectDay(params.value?.[0])
        const person = props.people[params.value?.[1]]
        return selectDay(params.value?.[3], person?.user.id)
      })
    }
    chart.setOption(props.mode === 'heat' ? heatOption() : barOption(), true)
    chart.resize()
    if (host.value) resizeObserver?.observe(host.value)
  } catch (failure) {
    chartError.value = true
    console.warn('Followup stats chart unavailable:', failure.message)
  }
}
onMounted(() => {
  draw()
  resizeObserver = new ResizeObserver(() => chart?.resize())
  if (host.value) resizeObserver.observe(host.value)
  motion.addEventListener('change', draw)
})
watch(() => [props.days, props.people, props.mode, props.teamAverage], draw, { deep: true })
onBeforeUnmount(() => { resizeObserver?.disconnect(); chart?.dispose(); motion.removeEventListener('change', draw) })
</script>
