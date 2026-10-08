<template>
  <main class="domestic-decision" aria-labelledby="decision-title">
    <div class="decision-aurora lg-aurora" aria-hidden="true"><div class="lg-aurora__blob lg-aurora__blob--gold" /><div class="lg-aurora__blob lg-aurora__blob--amber" /><div class="lg-aurora__blob lg-aurora__blob--peach" /></div>
    <header class="decision-heading"><p class="decision-eyebrow">DOMESTIC BUSINESS · DECISION WORKBENCH</p><h1 id="decision-title">内贸经营决策台</h1><p>从真实订单与客户记录出发，找到值得核对的变化，把判断落到行动。</p></header>
    <nav class="decision-tabs" role="tablist" aria-label="经营分析页签" @keydown="tabKeydown"><button v-for="([key, text], index) in tabs" :id="`decision-tab-${key}`" :key="key" role="tab" :aria-selected="tab === key" :aria-controls="`decision-panel-${key}`" :tabindex="tab === key ? 0 : -1" :data-index="index" @click="tab = key">{{ text }}</button></nav>
    <DecisionFilters :query="query" :applied="applied" :options="options" :permissions="permissions" :loading="loading" :views="views" :meta="analysis?.meta" :mutate="mutate" @apply="analyze" @refresh="refresh" @quality="qualityOpen = true" @views="loadViews" />
    <section v-if="loading" class="decision-panel" role="status" aria-live="polite"><p>正在读取授权范围，计算同一版本的经营事实…</p><el-skeleton :rows="8" animated /></section>
    <section v-else-if="error" class="decision-panel" role="alert"><el-result icon="error" title="分析暂未完成" :sub-title="error"><template #extra><GlassButton variant="primary" @click="refresh">刷新权限与分析</GlassButton></template></el-result></section>
    <template v-else-if="analysis">
      <div v-if="!analysis.meta.coverage_start || analysis.summary.customer_count < 10 || analysis.quality.order_reconciliation_count" class="decision-notice"><strong>观察限制</strong><span>{{ !analysis.meta.coverage_start ? '完整历史覆盖未确认；首次观察不代表真实新客。' : '' }} {{ analysis.summary.customer_count < 10 ? '当前购买客户少于10位，避免外推强趋势。' : '' }} {{ analysis.quality.order_reconciliation_count ? '整单与明细金额有差异，查看质量面板核验。' : '' }}</span></div>
      <section :id="`decision-panel-${tab}`" role="tabpanel" :aria-labelledby="`decision-tab-${tab}`" class="decision-tab-content" tabindex="0">
        <AnalysisPanels v-if="tab !== 'actions'" :tab="tab" :data="analysis" :query="query" :applied="applied" :options="options" @apply="analyze" @rows="openRows" @profile="openProfile" @evidence="openEvidence" @action="prepareAction" @tab="tab = $event" />
        <ActionReportPanel v-show="tab === 'actions'" ref="actionPanel" :data="analysis" :finance-allowed="permissions.finance" :report-allowed="permissions.report" :mutate="mutate" :failure="failure" @evidence="openEvidence" @customer="id => openProfile('customer', id)" @plan="applyPlan" />
      </section>
      <footer class="decision-footer"><span>当前状态重算 · 本公司成交需求样本 · 归因采用当前客户负责人</span><span>指标 {{ analysis.meta.metric_version }} · 规则 {{ analysis.meta.rule_version }} · 北京时间</span></footer>
    </template>
    <ProfileDrawer :state="profile" :finance-allowed="permissions.finance" @evidence="openEvidence" @customer="id => openProfile('customer', id)" @action="prepareAction" />
    <EvidenceDrawer :state="evidence" :failure="failure" />
    <QualityDrawer v-model="qualityOpen" :data="analysis" :options="options" :admin-allowed="permissions.admin" :mutate="mutate" :failure="failure" @refresh="refresh" @evidence="openEvidence" />
    <DetailDrawer v-model="drill.open" :title="drill.title" :width="760">
      <div class="action-bar"><el-select v-model="drill.kind" aria-label="明细类型" @change="drill.page = 1; drill.sort_field = ''; drill.sort_order = ''; loadRows()"><el-option label="匹配产品明细" value="items" /><el-option label="相关整单" value="orders" /><el-option label="客户" value="customers" /><el-option v-if="permissions.finance" label="资金流水" value="ledger" /><el-option v-if="permissions.finance" label="申请" value="requests" /></el-select><GlassButton @click="loadRows">重试明细</GlassButton></div>
      <p class="decision-note">同一快照下钻。相关整单额含未命中产品行，命中明细额仅含匹配行；跨组订单/客户不能相加。</p>
      <el-skeleton v-if="drill.loading" :rows="6" animated />
      <template v-else-if="drill.error"><el-alert type="error" :title="drill.error" :closable="false" /><GlassButton variant="primary" @click="refresh">刷新整组分析</GlassButton></template>
      <template v-else><DecisionTable :rows="drill.items" :columns="drillColumns" :paginate="false" remote-sort :sort-state="{ prop: drill.sort_field, order: drill.sort_order === 'asc' ? 'ascending' : drill.sort_order === 'desc' ? 'descending' : null }" @sort-change="sortDrill" action="原始证据" @open="openRowEvidence" /><el-pagination v-model:current-page="drill.page" v-model:page-size="drill.page_size" :page-sizes="[20, 50, 100]" :total="drill.total" layout="total, sizes, prev, pager, next" @current-change="loadRows" @size-change="drill.page = 1; loadRows()" /></template>
    </DetailDrawer>
  </main>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, provide, reactive, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { msgError, msgInfo, msgWarning } from '@/utils/feedback'
import { domesticDecisionApi as api } from '@/api/domesticDecision'
import { tableSortParams } from '@/utils/tableSort'
import { cleanQuery, FIELD_LABELS } from './state'
import { useDecisionWorkbench } from './composables/useDecisionWorkbench'
import DecisionFilters from './components/DecisionFilters.vue'
import AnalysisPanels from './components/AnalysisPanels.vue'
import ActionReportPanel from './components/ActionReportPanel.vue'
import ProfileDrawer from './components/ProfileDrawer.vue'
import EvidenceDrawer from './components/EvidenceDrawer.vue'
import QualityDrawer from './components/QualityDrawer.vue'
import DecisionTable from './components/DecisionTable.vue'
import './decision.css'
const { options, query, applied, analysis, loading, error, tab, tabs, permissions, views, profile, drill, qualityOpen, analyze, refresh, loadViews, openProfile, openRows, loadRows, mutate, failure } = useDecisionWorkbench()
const actionPanel = ref(null), evidence = reactive({ open: false, refs: [], title: '事实证据' })
const actionPreparing = ref(false)
let actionPreparationGeneration = 0
provide('decisionDictionaries', computed(() => options.value.dictionaries || {}))
provide('decisionMeta', computed(() => analysis.value?.meta))
watch(loading, value => { if (value) { evidence.open = false; evidence.refs = []; actionPreparationGeneration++; actionPreparing.value = false } })
onBeforeUnmount(() => { actionPreparationGeneration++ })
function openEvidence(refs) {
  const valid = Array.isArray(refs) ? refs.filter(row => row?.id && ['orders', 'order', 'items', 'item', ...(permissions.value.finance ? ['ledger', 'requests', 'request'] : [])].includes(row.type)) : []
  if (!valid.length) { msgInfo('当前没有可打开的记录证据'); return }
  evidence.refs = [...new Map(valid.map(row => [`${row.type}:${row.id}`, row])).values()]; evidence.open = true
}
async function prepareAction(insight) {
  if (!permissions.value.action) { msgWarning('需要内部行动写入权限'); return }
  if (!insight.customer_id) { msgWarning('群体结论不能直接创建客户行动'); return }
  if (actionPreparing.value || !analysis.value || !applied.value) return
  const originalRunId = analysis.value.meta.run_id, token = ++actionPreparationGeneration
  actionPreparing.value = true
  try {
    let selected = analysis.value.insights.find(row => insight.insight_id && row.insight_id === insight.insight_id)
    if (!selected) {
      msgInfo('正在核验该画像的最新行动证据')
      const customerRun = await api.analyze({ ...JSON.parse(JSON.stringify(applied.value)), customer_ids: [insight.customer_id], owner_ids: [], filters: {}, finance_related_customers: false })
      if (token !== actionPreparationGeneration || originalRunId !== analysis.value?.meta.run_id) return
      selected = customerRun.insights.find(row => row.customer_id === insight.customer_id && row.rule_key === insight.rule_key)
      if (!selected) { msgInfo('最新证据未再触发该建议，请核对画像事实后重新选择'); return }
      selected = { ...selected, source_run_id: customerRun.meta.run_id }
    } else selected = { ...selected, source_run_id: originalRunId }
    if (token !== actionPreparationGeneration) return
    profile.open = false; tab.value = 'actions'; await nextTick(); actionPanel.value?.prepareAction(selected)
  } catch (cause) { if (token === actionPreparationGeneration) msgError(failure(cause), cause) }
  finally { if (token === actionPreparationGeneration) actionPreparing.value = false }
}
async function applyPlan(plan) {
  const valid = cleanQuery(plan.query, options.value)
  Object.assign(query, valid); tab.value = tabs.value.some(([key]) => key === plan.target_tab) ? plan.target_tab : 'overview'; await analyze()
}
function tabKeydown(event) {
  const buttons = [...event.currentTarget.querySelectorAll('[role="tab"]')], index = buttons.indexOf(document.activeElement)
  if (index < 0 || !['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(event.key)) return
  event.preventDefault(); const next = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length
  tab.value = tabs.value[next][0]; buttons[next].focus()
}
const col = (key, label, format) => ({ key, label, format })
const drillColumns = computed(() => {
  if (drill.kind === 'orders') return [col('id', '订单ID'), col('domestic_no', '订单号'), col('order_date', '订单日期'), col('customer_id', '客户ID'), col('order_category', '订单类别'), col('order_type', '订单类型'), col('status', '当前状态'), col('total_amount', '相关整单额', 'money')]
  if (drill.kind === 'items') return [col('id', '明细ID'), col('order_id', '订单ID'), ...['product_type', 'craft', 'net_color', 'size', 'length', 'density', 'hair_style_series', 'color'].map(field => col(`attrs.${field}`, FIELD_LABELS[field])), col('order_qty', '数量', 'number'), col('unit_price', '成交单价', 'money'), col('amount', '命中明细额', 'money')]
  if (drill.kind === 'customers') return [col('customer_id', '客户ID'), col('shop_name', '客户'), col('amount', '相关整单额', 'money'), col('matched_amount', '匹配明细额', 'money'), col('history.cycle_status', '节奏')]
  if (drill.kind === 'ledger') return [col('id', '流水ID'), col('customer_id', '客户ID'), col('order_id', '订单ID'), col('transaction_type', '流水类型'), col('amount', '金额', 'money'), col('balance_before', '发生前', 'money'), col('balance_after', '发生后', 'money'), col('created_at', '北京时间')]
  return [col('id', '申请ID'), col('customer_id', '客户ID'), col('request_type', '申请类型'), col('amount', '金额', 'money'), col('status', '当前审核状态'), col('created_at', '创建时间')]
})
function openRowEvidence(row) { if (drill.kind === 'customers') openProfile('customer', row.customer_id); else openEvidence([{ type: drill.kind, id: row.id }]) }
function sortDrill(sort) { const params = tableSortParams(sort); drill.sort_field = params.sort_field || ''; drill.sort_order = params.sort_order || ''; drill.page = 1; loadRows() }
onMounted(async () => { await refresh(); loadViews() })
</script>
