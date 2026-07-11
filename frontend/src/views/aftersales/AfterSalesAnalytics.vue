<template>
  <div v-loading="loading" class="analytics-page">
    <div class="page-heading"><div><h1>售后分析</h1><p>从问题、状态和赔偿成本识别需要优先复盘的产品与流程。</p></div><GlassButton variant="secondary" left-icon="Refresh" @click="fetchData">刷新</GlassButton></div>
    <div class="metric-grid">
      <article><span>售后单总量</span><strong>{{ data.total || 0 }}</strong><small>当前授权范围</small></article>
      <article><span>累计赔偿成本</span><strong>USD {{ data.compensation_total_usd || '0.00' }}</strong><small>按估算成本统一口径</small></article>
      <article><span>高频问题类型</span><strong>{{ topIssue?.name || '—' }}</strong><small>{{ topIssue ? `${topIssue.count} 单` : '暂无数据' }}</small></article>
      <article><span>平均闭环时长</span><strong>{{ data.average_resolution_hours == null ? '—' : `${data.average_resolution_hours}h` }}</strong><small>从登记到关闭</small></article>
    </div>
    <div class="analysis-grid">
      <section class="chart-card"><h2>问题类型分布</h2><div v-for="item in data.by_issue || []" :key="item.name" class="bar-row"><span>{{ item.name }}</span><div><i :style="{ transform: `scaleX(${barScale(item.count, maxIssue)})` }"></i></div><strong>{{ item.count }}</strong></div><el-empty v-if="!data.by_issue?.length" description="暂无问题数据" /></section>
      <section class="chart-card"><h2>流程状态</h2><div class="status-list"><div v-for="item in data.by_status || []" :key="item.name"><el-tag effect="plain">{{ STATUS_LABELS[item.name] || item.name }}</el-tag><strong>{{ item.count }}</strong></div></div><el-empty v-if="!data.by_status?.length" description="暂无状态数据" /></section>
      <section class="chart-card"><h2>高频产品</h2><div class="rank-list"><div v-for="item in data.by_product || []" :key="item.name"><span>{{ item.name }}</span><strong>{{ item.count }} 单</strong></div></div><el-empty v-if="!data.by_product?.length" description="暂无产品数据" /></section>
      <section class="chart-card"><h2>批次风险</h2><div class="rank-list"><div v-for="item in data.by_batch || []" :key="item.name"><span>{{ item.name }}</span><strong>{{ item.count }} 单</strong></div></div><el-empty v-if="!data.by_batch?.length" description="暂无批次数据" /></section>
      <section class="chart-card"><h2>客户等级 / 责任分类</h2><div class="split-summary"><div><span>客户等级</span><el-tag v-for="item in data.by_customer_grade || []" :key="item.name" effect="plain">{{ item.name }} · {{ item.count }}</el-tag></div><div><span>责任分类</span><el-tag v-for="item in data.by_responsibility || []" :key="item.name" effect="plain">{{ item.name }}类 · {{ item.count }}</el-tag></div></div></section>
      <section class="chart-card"><h2>售后量与赔偿趋势</h2><div class="rank-list"><div v-for="item in data.trend || []" :key="item.date"><span>{{ item.date }} · {{ item.count }} 单</span><strong>USD {{ item.compensation_usd }}</strong></div></div><el-empty v-if="!data.trend?.length" description="暂无趋势数据" /></section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { getAfterSalesAnalytics } from '@/api/aftersales'
import { STATUS_LABELS } from './aftersalesRules'
const loading = ref(false); const data = ref({ total: 0, by_issue: [], by_status: [], by_product: [], by_batch: [], by_customer_grade: [], by_responsibility: [], trend: [] })
const topIssue = computed(() => [...(data.value.by_issue || [])].sort((a, b) => b.count - a.count)[0])
const maxIssue = computed(() => Math.max(1, ...(data.value.by_issue || []).map(item => item.count)))
function barScale(count, maxRef) { return Math.max(0, Math.min(1, count / maxRef.value)) }
async function fetchData() { loading.value = true; try { const response = await getAfterSalesAnalytics(); data.value = response.data || data.value } finally { loading.value = false } }
onMounted(fetchData)
</script>

<style scoped>
.page-heading { display: flex; justify-content: space-between; gap: 16px; margin-bottom: 20px; }.page-heading h1 { margin: 0 0 4px; color: var(--text-primary); font: 700 20px/1.3 var(--font-display); }.page-heading p { margin: 0; color: var(--text-secondary); font-size: 13px; }.metric-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 16px; }.metric-grid article, .chart-card { padding: 18px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); box-shadow: var(--card-shadow); }.metric-grid article { display: grid; gap: 6px; }.metric-grid span, .metric-grid small { color: var(--text-secondary); font-size: 12px; }.metric-grid strong { color: var(--text-primary); font: 700 24px/1.2 var(--font-display); font-variant-numeric: tabular-nums; }.analysis-grid { display: grid; grid-template-columns: 1.3fr .7fr; gap: 16px; margin-top: 16px; }.chart-card h2 { margin: 0 0 16px; color: var(--text-primary); font-size: 15px; }.bar-row { display: grid; grid-template-columns: 100px 1fr 36px; gap: 10px; align-items: center; margin: 10px 0; color: var(--text-secondary); font-size: 12px; }.bar-row div { height: 8px; overflow: hidden; border-radius: 999px; background: var(--toolbar-bg); }.bar-row i { display: block; width: 100%; height: 100%; transform-origin: left; border-radius: inherit; background: var(--color-primary); }.bar-row strong { text-align: right; font-variant-numeric: tabular-nums; }.status-list { display: grid; gap: 10px; }.status-list div { display: flex; justify-content: space-between; align-items: center; }.status-list strong { color: var(--text-primary); font-variant-numeric: tabular-nums; }
.metric-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }.analysis-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }.rank-list, .split-summary { display: grid; gap: 10px; }.rank-list > div { display: flex; justify-content: space-between; gap: 12px; color: var(--text-secondary); font-size: 12px; }.rank-list strong { color: var(--text-primary); font-variant-numeric: tabular-nums; }.split-summary > div { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }.split-summary span { min-width: 68px; color: var(--text-secondary); font-size: 12px; }
@media (max-width: 900px) { .metric-grid, .analysis-grid { grid-template-columns: 1fr; } }
</style>
