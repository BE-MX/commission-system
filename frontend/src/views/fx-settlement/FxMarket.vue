<template>
  <section class="market-panel lg-card is-static" aria-label="美元兑人民币行情">
    <div class="panel-heading">
      <div><span class="eyebrow">USD / CNY</span><h3>先看行情，再定金额</h3></div>
      <GlassButton class="refresh-button" variant="ghost" :loading="loading" @click="$emit('refresh')">刷新行情</GlassButton>
    </div>
    <p v-if="error" class="warning" role="alert">{{ error }}。可填写银行当前报价继续测算。</p>
    <div class="quote-grid">
      <div class="current-rate">
        <span>银行现汇买入参考价</span>
        <strong>{{ market?.quote ? Number(market.quote.rate).toFixed(4) : '—' }}</strong>
        <p>1 美元可换人民币 · 数值越高，结汇越有利</p>
        <p v-if="market?.quote" :class="fresh ? 'muted' : 'warning'">
          {{ formatBeijingDateTime(market.quote.as_of) }} · {{ fresh ? '30 分钟内参考报价' : '报价已过期' }}
        </p>
        <p v-else class="muted">{{ loading ? '正在获取公开报价…' : '暂无可用报价' }}</p>
        <p v-if="market?.intraday" :class="changeClass(market.intraday.change_pct)">较 {{ formatBeijingDateTime(market.intraday.from_at, { seconds: false }) }} 的参考价 {{ change(market.intraday.change_pct) }}</p>
      </div>
      <div class="trend-stat"><span>最近 5 个观测日</span><strong :class="changeClass(market?.trend?.change_5d_pct)">{{ change(market?.trend?.change_5d_pct) }}</strong><p>美元兑人民币变动</p></div>
      <div class="trend-stat"><span>最近 20 个观测日</span><strong :class="changeClass(market?.trend?.change_20d_pct)">{{ change(market?.trend?.change_20d_pct) }}</strong><p>{{ market?.trend?.usable ? '日度趋势可供参考' : '趋势缺失或已过期' }}</p></div>
    </div>
    <div v-show="market?.history?.length" ref="chartElement" class="history-chart" role="img" aria-label="美元兑人民币最近90个观测日至今的汇率图" />
    <FxWeeklyHighs :history="market?.history" :today="today" />
    <div class="market-source">
      <span v-if="market?.trend">历史截至 {{ market.trend.as_of }}，滞后 {{ market.trend.lag_days }} 天；按周发布，不是实时走势。</span>
      <span v-else>历史数据获取后显示趋势。</span>
      <span v-if="chartData">图表显示到 {{ today }}；{{ chartData.showQuote ? '圆点为按实际日期标出的中国银行参考价，虚线仅连接不同来源报价，不代表连续行情。' : '银行报价未覆盖历史之后的日期，末端不补造价格。' }}</span>
      <span>来源：<a href="https://www.boc.cn/sourcedb/whpj/" target="_blank" rel="noopener noreferrer">中国银行</a> / <a href="https://fred.stlouisfed.org/series/DEXCHUS" target="_blank" rel="noopener noreferrer">美联储 FRED</a>。公开价仅供参考，以你的银行实际成交价为准。</span>
    </div>
    <p v-for="warning in market?.warnings || []" :key="warning" class="warning">{{ warning }}</p>
  </section>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart, ScatterChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import GlassButton from '@/components/GlassButton.vue'
import { currentBeijingDate, formatBeijingDateTime, parseApiDateTime } from '@/utils/datetime'
import { buildMarketChartData } from './marketChartData'
import FxWeeklyHighs from './FxWeeklyHighs.vue'

echarts.use([LineChart, ScatterChart, GridComponent, TooltipComponent, CanvasRenderer])
const props = defineProps({ market: Object, loading: Boolean, error: String, clock: Number })
defineEmits(['refresh'])
const chartElement = ref(null)
let chart, observer
const fresh = computed(() => props.market?.quote?.usable && props.clock - parseApiDateTime(props.market.quote.as_of).getTime() <= 1800000)
const today = computed(() => currentBeijingDate(new Date(props.clock)))
const chartData = computed(() => buildMarketChartData(props.market, today.value))
const change = value => value == null ? '—' : `${value > 0 ? '+' : ''}${Number(value).toFixed(2)}%`
const changeClass = value => value == null ? '' : value < 0 ? 'down' : 'up'

async function renderChart() {
  await nextTick()
  if (!chartElement.value || !chartData.value) return
  chart ||= echarts.init(chartElement.value)
  const style = getComputedStyle(chartElement.value)
  const color = name => style.getPropertyValue(name).trim()
  const data = chartData.value
  chart.setOption({
    animation: false,
    grid: { left: 48, right: 18, top: 16, bottom: 28 },
    tooltip: { trigger: 'axis', confine: true, valueFormatter: value => Number(value).toFixed(4) },
    xAxis: { type: 'category', data: data.dates, boundaryGap: true, axisLabel: { color: color('--text-secondary'), formatter: value => value.slice(5), showMaxLabel: true }, axisLine: { lineStyle: { color: color('--border-color') } }, axisTick: { show: false } },
    yAxis: { type: 'value', scale: true, axisLabel: { color: color('--text-secondary') }, splitLine: { lineStyle: { color: color('--border-color') } } },
    series: [
      { name: 'FRED 历史报价', type: 'line', data: data.historyRates, showSymbol: false, lineStyle: { color: color('--color-primary'), width: 2 }, itemStyle: { color: color('--color-primary') } },
      { name: '不同来源连接', type: 'line', data: data.connectionRates, connectNulls: false, showSymbol: false, tooltip: { show: false }, lineStyle: { color: color('--text-secondary'), width: 1, type: 'dashed' } },
      { name: '中国银行现汇买入参考价', type: 'scatter', data: data.quoteRates.flatMap((rate, index) => rate == null ? [] : [[data.dates[index], rate]]), symbolSize: 12, itemStyle: { color: color('--color-primary-hover'), borderColor: color('--card-bg'), borderWidth: 2 } },
    ],
  })
  chart.resize()
}
watch(chartData, renderChart)
onMounted(() => {
  observer = new ResizeObserver(() => chart?.resize())
  observer.observe(chartElement.value)
  renderChart()
})
onBeforeUnmount(() => { observer?.disconnect(); chart?.dispose() })
</script>

<style scoped>
.market-panel { padding: 22px 24px; }
.panel-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.eyebrow { font: 700 11px var(--font-display); color: var(--color-primary-text); letter-spacing: .1em; }
h3 { margin: 5px 0 20px; font-size: 17px; }
.quote-grid { display: grid; grid-template-columns: 1.6fr 1fr 1fr; gap: 24px; }
.quote-grid span, .quote-grid p, .market-source { font-size: 12px; color: var(--text-secondary); }
.quote-grid strong { display: block; font: 700 28px var(--font-display); margin: 8px 0; font-variant-numeric: tabular-nums; }
.current-rate strong { font-size: 38px; }
.quote-grid p { margin: 5px 0; }
.trend-stat { padding-top: 8px; }
.down { color: var(--color-danger-text); }.up { color: var(--color-success-text); }
.warning { color: var(--color-warning-text) !important; font-size: 12px; }
.history-chart { height: 200px; width: 100%; margin-top: 12px; }
.market-source { display: grid; gap: 4px; line-height: 1.6; }
a { color: var(--color-primary-text); text-underline-offset: 3px; }
@media(max-width:650px) { .market-panel { padding: 18px; }.quote-grid { grid-template-columns: 1fr 1fr; gap: 12px; }.current-rate { grid-column: 1/-1; }.history-chart { height: 180px; }.panel-heading { gap: 8px; }.panel-heading h3 { font-size: 15px; }.refresh-button { min-height: 44px; flex-shrink: 0; } }
</style>
