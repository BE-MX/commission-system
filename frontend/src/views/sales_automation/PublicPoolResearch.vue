<template>
  <div class="sales-page">
    <header class="page-heading">
      <div>
        <h1>公海客户背调</h1>
        <p>按历史订单、企业身份锚点和低信息量联系方式分档。Agent 只补全证据与开发草稿，由业务员确认后才进入机会雷达。</p>
      </div>
      <div class="heading-actions">
        <GlassButton v-permission="'sales_automation:admin'" variant="secondary" left-icon="Refresh" :loading="auditLoading" @click="refreshAudit">重新审计</GlassButton>
        <GlassButton v-any-permission="['sales_automation:write', 'sales_automation:admin']" variant="primary" left-icon="Plus" :loading="batchLoading" @click="generateBatch">生成今日批次</GlassButton>
      </div>
    </header>

    <section class="metric-grid">
      <article v-for="item in metrics" :key="item.key" class="surface-card metric-card">
        <span>{{ item.label }}</span><strong>{{ number(audit[item.key]) }}</strong><small>{{ item.note }}</small>
      </article>
    </section>

    <div class="toolbar">
      <el-input v-model="filters.keyword" clearable placeholder="客户名称 / OKKI ID" class="keyword-filter" @keyup.enter="search" @clear="search" />
      <el-select v-model="filters.tier" clearable placeholder="全部分档" style="width: 130px" @change="search">
        <el-option label="T1 历史订单" value="T1" /><el-option label="T2 身份完善" value="T2" /><el-option label="T3 低信息量" value="T3" />
      </el-select>
      <el-select v-model="filters.status" clearable placeholder="全部进度" style="width: 130px" @change="search">
        <el-option label="待领取" value="pending" /><el-option label="背调中" value="running" /><el-option label="已完成" value="completed" /><el-option label="失败" value="failed" />
      </el-select>
      <el-select v-model="filters.review_status" clearable placeholder="全部审核" style="width: 130px" @change="search">
        <el-option label="待审核" value="pending" /><el-option label="已确认" value="approved" /><el-option label="已拒绝" value="rejected" />
      </el-select>
      <GlassButton variant="primary" left-icon="Search" @click="search">查询</GlassButton>
      <GlassButton variant="secondary" left-icon="Refresh" :loading="loading" @click="fetchTasks">刷新</GlassButton>
    </div>

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="tasks" border class="list-table">
        <el-table-column label="客户" min-width="210">
          <template #default="{ row }"><div class="company-cell"><strong>{{ row.subject.display_name }}</strong><span>{{ row.subject.country || '地区未知' }} · OKKI {{ row.subject.source_customer_id }}</span></div></template>
        </el-table-column>
        <el-table-column label="档位" width="105"><template #default="{ row }"><el-tag :type="tierMeta(row.tier).type">{{ tierMeta(row.tier).label }}</el-tag></template></el-table-column>
        <el-table-column label="订单 / 完整度" min-width="145"><template #default="{ row }">{{ row.subject.order_count }} 单 / {{ row.subject.completeness_score }}%</template></el-table-column>
        <el-table-column label="背调进度" width="105"><template #default="{ row }"><el-tag :type="statusMeta(row.status).type" effect="plain">{{ statusMeta(row.status).label }}</el-tag></template></el-table-column>
        <el-table-column label="成交等级" width="110"><template #default="{ row }"><span v-if="row.assessment" class="grade" :data-grade="row.assessment.grade">{{ row.assessment.grade }}</span><span v-else>-</span></template></el-table-column>
        <el-table-column label="证据置信度" width="115"><template #default="{ row }">{{ confidenceLabel(row.assessment?.evidence_confidence) }}</template></el-table-column>
        <el-table-column label="人工审核" width="105"><template #default="{ row }"><el-tag :type="reviewMeta(row.review_status).type" effect="plain">{{ reviewMeta(row.review_status).label }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="190" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="openDetail(row)">详情</GlassButton>
            <template v-if="row.status === 'completed' && row.review_status === 'pending'">
              <GlassButton v-any-permission="['sales_automation:write', 'sales_automation:admin']" variant="link" link-tone="success" left-icon="Check" @click="approve(row)">进入开发</GlassButton>
              <GlassButton v-any-permission="['sales_automation:write', 'sales_automation:admin']" variant="link" link-tone="danger" left-icon="Close" @click="reject(row)">拒绝</GlassButton>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination v-model:current-page="page" v-model:page-size="pageSize" :total="total" :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next" class="pager" @current-change="handlePageChange" @size-change="handleSizeChange" />
    </section>

    <DetailDrawer v-model="detailVisible" :title="detail ? `公海背调 · ${detail.subject.display_name}` : '公海背调'" width="min(820px, 94vw)" :loading="detailLoading">
      <template v-if="detail">
        <div class="detail-summary">
          <div><el-tag :type="tierMeta(detail.tier).type">{{ tierMeta(detail.tier).label }}</el-tag><h2>{{ detail.subject.display_name }}</h2><p>{{ detail.selection_reason?.join('；') }}</p></div>
          <div v-if="detail.assessment" class="score-stack"><strong>{{ detail.assessment.grade }}</strong><span>优先分 {{ detail.assessment.priority_score }}</span></div>
        </div>
        <el-tabs v-model="activeTab">
          <el-tab-pane label="OKKI 原始线索" name="seed">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="企业邮箱">{{ detail.subject.primary_email || '-' }}</el-descriptions-item><el-descriptions-item label="独立站"><a v-if="detail.subject.website" :href="detail.subject.website" target="_blank" rel="noopener noreferrer">打开官网</a><span v-else>-</span></el-descriptions-item>
              <el-descriptions-item label="历史订单">{{ detail.subject.order_count }} 单</el-descriptions-item><el-descriptions-item label="历史金额">USD {{ number(detail.subject.order_amount_usd) }}</el-descriptions-item>
              <el-descriptions-item label="最近订单">{{ formatTime(detail.subject.last_order_at) }}</el-descriptions-item><el-descriptions-item label="电话">{{ detail.subject.primary_phone || '-' }}</el-descriptions-item>
            </el-descriptions>
          </el-tab-pane>
          <el-tab-pane label="公开证据" name="evidence">
            <p class="summary-text">{{ detail.research?.summary || 'Agent 尚未提交研究。' }}</p>
            <article v-for="fact in detail.research?.facts || []" :key="fact.id" class="evidence-card"><p>{{ fact.claim }}</p><div class="evidence-meta"><span>置信度 {{ Math.round(fact.confidence * 100) }}%</span><span>{{ formatTime(fact.captured_at) }}</span><a :href="fact.source_url" target="_blank" rel="noopener noreferrer">打开来源</a></div></article>
            <div v-if="!detail.research?.facts?.length" class="empty-hint">暂无可引用事实；身份不可验证时允许诚实留空。</div>
          </el-tab-pane>
          <el-tab-pane label="成交研判" name="assessment">
            <template v-if="detail.assessment">
              <el-descriptions :column="2" border><el-descriptions-item label="等级 / 可能性">{{ detail.assessment.grade }} / {{ likelihoodLabel(detail.assessment.deal_likelihood) }}</el-descriptions-item><el-descriptions-item label="身份判断">{{ identityLabel(detail.assessment.identity_decision) }}</el-descriptions-item><el-descriptions-item label="业务质量分">{{ detail.assessment.business_quality_score }}</el-descriptions-item><el-descriptions-item label="成交分">{{ detail.assessment.deal_score }}</el-descriptions-item><el-descriptions-item label="供应商状态">{{ supplierLabel(detail.assessment.supplier_status) }}</el-descriptions-item><el-descriptions-item label="证据置信度">{{ confidenceLabel(detail.assessment.evidence_confidence) }}</el-descriptions-item></el-descriptions>
              <h3>建议策略</h3><p class="summary-text">{{ detail.assessment.recommended_strategy }}</p>
              <h3>英文开场草稿（未发送）</h3><p class="draft-text">{{ detail.assessment.opening_message_en || '未生成' }}</p>
              <h3>痛点 / 匹配 / 风险</h3><div class="tag-list"><el-tag v-for="item in detail.assessment.pain_points" :key="`p-${item}`" type="warning" effect="plain">{{ item }}</el-tag><el-tag v-for="item in detail.assessment.product_fit" :key="`f-${item}`" type="success" effect="plain">{{ item }}</el-tag><el-tag v-for="item in detail.assessment.risks" :key="`r-${item}`" type="danger" effect="plain">{{ item }}</el-tag></div>
            </template><div v-else class="empty-hint">等待 Agent 背调与成交研判。</div>
          </el-tab-pane>
        </el-tabs>
      </template>
    </DetailDrawer>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessageBox } from 'element-plus'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { approvePublicPoolTask, createPublicPoolBatch, getPublicPoolAudit, getPublicPoolTask, getPublicPoolTasks, refreshPublicPoolAudit, rejectPublicPoolTask } from '@/api/salesAutomation'
import { useListPage } from '@/composables/useListPage'
import { msgSuccess } from '@/utils/feedback'

const audit = ref({}); const auditLoading = ref(false); const batchLoading = ref(false)
const metrics = computed(() => [
  { key: 'public_customers', label: '公海客户', note: 'owner_user_ids 为空' }, { key: 'tier_t1', label: 'T1 历史订单', note: '优先二次激活' },
  { key: 'tier_t2', label: 'T2 身份完善', note: '企业邮箱 / 官网 / 社媒' }, { key: 'tier_t3', label: 'T3 低信息量', note: '私人邮箱 / 电话 / WhatsApp' },
  { key: 'cold_storage', label: '冷藏区', note: '暂无可用身份锚点' },
])
const tierMeta = v => ({ T1: { label: 'T1 再激活', type: 'danger' }, T2: { label: 'T2 优质', type: 'success' }, T3: { label: 'T3 探索', type: 'info' } }[v] || { label: v || '-', type: 'info' })
const statusMeta = v => ({ pending: { label: '待领取', type: 'info' }, running: { label: '背调中', type: 'warning' }, completed: { label: '已完成', type: 'success' }, failed: { label: '失败', type: 'danger' } }[v] || { label: v || '-', type: 'info' })
const reviewMeta = v => ({ pending: { label: '待审核', type: 'warning' }, approved: { label: '已确认', type: 'success' }, rejected: { label: '已拒绝', type: 'info' } }[v] || { label: v || '-', type: 'info' })
const confidenceLabel = v => ({ high: '高', medium: '中', low: '低' }[v] || '-')
const likelihoodLabel = v => ({ high: '较高', medium: '中等', low: '较低' }[v] || '-')
const identityLabel = v => ({ confirmed: '已确认', candidate: '候选匹配', unverifiable: '无法验证', rejected: '主体不符' }[v] || '-')
const supplierLabel = v => ({ stable: '已有稳定供应商', looking: '正在寻找', switching: '可能切换', unknown: '未知' }[v] || '-')
const number = v => Number(v || 0).toLocaleString('zh-CN'); const formatTime = v => v ? new Date(v).toLocaleString('zh-CN', { hour12: false }) : '-'

const { loading, list: tasks, total, page, pageSize, searchForm: filters, fetchList: fetchTasks, handleSearch: search, handlePageChange, handleSizeChange } = useListPage(async params => {
  const clean = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== '')); const res = await getPublicPoolTasks(clean); return res.data || {}
}, { searchForm: { keyword: '', tier: '', status: '', review_status: '' } })
const detailVisible = ref(false); const detailLoading = ref(false); const detail = ref(null); const activeTab = ref('seed')
async function loadAudit() { auditLoading.value = true; try { audit.value = (await getPublicPoolAudit()).data || {} } finally { auditLoading.value = false } }
async function refreshAudit() { auditLoading.value = true; try { audit.value = (await refreshPublicPoolAudit()).data || {}; msgSuccess('公海审计') } finally { auditLoading.value = false } }
async function generateBatch() { batchLoading.value = true; try { await createPublicPoolBatch({ quota_per_tier: 20, policy_version: 'v1' }); msgSuccess('今日批次生成'); await Promise.all([loadAudit(), fetchTasks()]) } finally { batchLoading.value = false } }
async function openDetail(row) { detailVisible.value = true; detailLoading.value = true; activeTab.value = 'seed'; try { detail.value = (await getPublicPoolTask(row.id)).data } finally { detailLoading.value = false } }
async function approve(row) { await approvePublicPoolTask(row.id); msgSuccess('进入开发队列'); await fetchTasks(); if (detail.value?.id === row.id) detail.value = (await getPublicPoolTask(row.id)).data }
async function reject(row) { try { const { value } = await ElMessageBox.prompt('请填写拒绝原因，便于后续调整筛选和背调策略。', '拒绝公海客户', { inputType: 'textarea', inputValidator: v => Boolean(v?.trim()) || '拒绝原因不能为空' }); await rejectPublicPoolTask(row.id, value.trim()); msgSuccess('拒绝'); await fetchTasks() } catch (error) { if (error !== 'cancel' && error !== 'close') throw error } }
onMounted(loadAudit)
</script>

<style scoped>
@import './salesAutomation.css';
.heading-actions,.tag-list { display: flex; flex-wrap: wrap; gap: 8px; }.metric-grid { display: grid; grid-template-columns: repeat(5,minmax(0,1fr)); gap: 12px; margin-bottom: 18px; }.metric-card { display: grid; gap: 4px; padding: 14px 16px; }.metric-card span,.metric-card small,.company-cell span,.detail-summary p,.score-stack span { color: var(--text-muted); font-size: 12px; }.metric-card strong { color: var(--text-primary); font: 700 24px/1.2 var(--font-display); }.keyword-filter { width: 230px; }.company-cell { display: grid; gap: 4px; }.company-cell strong { color: var(--text-primary); }.grade { color: var(--color-primary); font-size: 20px; font-weight: 800; }.detail-summary { display: flex; justify-content: space-between; gap: 16px; padding: 14px; margin-bottom: 12px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--toolbar-bg); }.detail-summary h2 { margin: 8px 0 4px; color: var(--text-primary); font-size: 18px; }.detail-summary p { margin: 0; }.score-stack { display: grid; align-content: center; text-align: center; min-width: 80px; }.score-stack strong { color: var(--color-primary); font-size: 30px; }.summary-text,.draft-text { color: var(--text-secondary); line-height: 1.7; white-space: pre-wrap; }.draft-text { padding: 12px; border: 1px solid var(--border-color); border-radius: 8px; background: var(--toolbar-bg); }h3 { margin: 20px 0 8px; color: var(--text-primary); font-size: 14px; }a { color: var(--color-primary); text-decoration: none; }a:hover { text-decoration: underline; }@media(max-width:1100px){.metric-grid{grid-template-columns:repeat(3,1fr)}}@media(max-width:720px){.heading-actions{width:100%}.metric-grid{grid-template-columns:repeat(2,1fr)}.keyword-filter{width:100%}}
</style>
