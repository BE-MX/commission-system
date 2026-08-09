<template>
  <div class="sales-page">
    <header class="page-heading">
      <div>
        <h1>客户池</h1>
        <p>公司以官网域名作为唯一身份。先看匹配理由与研究证据，再确认进入正式开发队列。</p>
      </div>
    </header>

    <div class="toolbar">
      <el-input v-model="filters.keyword" clearable placeholder="搜索公司名称" class="lead-filter" @keyup.enter="search" @clear="search" />
      <el-select v-model="filters.status" clearable placeholder="全部状态" style="width: 150px" @change="search">
        <el-option label="待确认" value="candidate" />
        <el-option label="已确认" value="approved" />
        <el-option label="已拒绝" value="rejected" />
      </el-select>
      <GlassButton variant="primary" left-icon="Search" @click="search">查询</GlassButton>
      <GlassButton variant="secondary" left-icon="Refresh" :loading="loading" @click="fetchLeads">刷新</GlassButton>
    </div>

    <section class="surface-card table-card">
      <el-table v-loading="loading" :data="leads" border class="list-table">
        <el-table-column label="公司" min-width="200">
          <template #default="{ row }">
            <div class="company-cell">
              <strong>{{ row.name }}</strong>
              <a :href="row.website" target="_blank" rel="noopener noreferrer">{{ row.domain }}</a>
            </div>
          </template>
        </el-table-column>
        <el-table-column prop="country" label="国家/地区" min-width="115" show-overflow-tooltip />
        <el-table-column prop="industry" label="行业" min-width="140" show-overflow-tooltip />
        <el-table-column label="匹配分" min-width="100" sortable prop="match_score">
          <template #default="{ row }"><span class="score">{{ Math.round(row.match_score) }}</span></template>
        </el-table-column>
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }"><el-tag :type="leadStatus(row.status).type" effect="light">{{ leadStatus(row.status).label }}</el-tag></template>
        </el-table-column>
        <el-table-column label="联系人 / 有效邮箱" min-width="145">
          <template #default="{ row }">{{ row.contact_count }} / {{ row.valid_email_count }}</template>
        </el-table-column>
        <el-table-column label="研究" min-width="100">
          <template #default="{ row }"><el-tag :type="researchStatus(row.research_status).type" effect="plain">{{ researchStatus(row.research_status).label }}</el-tag></template>
        </el-table-column>
        <el-table-column label="更新时间" min-width="155">
          <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click="openDetail(row)">详情</GlassButton>
            <GlassButton
              v-if="row.status === 'candidate'"
              v-any-permission="['sales_automation:write', 'sales_automation:admin']"
              variant="link"
              link-tone="success"
              left-icon="Check"
              :loading="approvingId === row.id"
              @click="approve(row)"
            >确认</GlassButton>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </section>

    <DetailDrawer v-model="detailVisible" :title="detail ? `客户详情 · ${detail.name}` : '客户详情'" width="min(760px, 92vw)" :loading="detailLoading">
      <template v-if="detail">
        <div class="detail-summary">
          <div>
            <h2>{{ detail.name }}</h2>
            <a :href="detail.website" target="_blank" rel="noopener noreferrer">{{ detail.domain }}</a>
          </div>
          <div class="score-badge"><strong>{{ Math.round(detail.match_score) }}</strong><span>匹配分</span></div>
        </div>

        <el-tabs v-model="activeTab">
          <el-tab-pane label="公司与评分" name="company">
            <el-descriptions :column="2" border>
              <el-descriptions-item label="国家/地区">{{ detail.country || '-' }}</el-descriptions-item>
              <el-descriptions-item label="行业">{{ detail.industry || '-' }}</el-descriptions-item>
              <el-descriptions-item label="状态">{{ leadStatus(detail.status).label }}</el-descriptions-item>
              <el-descriptions-item label="负责人">{{ detail.owner_user_id || '待分配' }}</el-descriptions-item>
            </el-descriptions>
            <h3 class="detail-section-title">匹配理由</h3>
            <div class="tag-list">
              <el-tag v-for="reason in detail.score_reasons || []" :key="reason" effect="plain">{{ reason }}</el-tag>
              <span v-if="!detail.score_reasons?.length" class="muted">暂无匹配理由</span>
            </div>
            <h3 class="detail-section-title">公司简介</h3>
            <p class="summary-text">{{ detail.description || '暂无简介' }}</p>
          </el-tab-pane>

          <el-tab-pane :label="`联系人 (${detail.contacts?.length || 0})`" name="contacts">
            <el-table v-if="detail.contacts?.length" :data="detail.contacts" border>
              <el-table-column prop="name" label="姓名" min-width="110" />
              <el-table-column prop="role" label="职位" min-width="140" show-overflow-tooltip />
              <el-table-column prop="email" label="邮箱" min-width="190" show-overflow-tooltip />
              <el-table-column label="验证" width="90">
                <template #default="{ row }"><el-tag :type="emailStatus(row.email_status).type" effect="plain">{{ emailStatus(row.email_status).label }}</el-tag></template>
              </el-table-column>
              <el-table-column label="证据" width="70">
                <template #default="{ row }"><a :href="row.source_url" target="_blank" rel="noopener noreferrer">来源</a></template>
              </el-table-column>
            </el-table>
            <div v-else class="empty-hint">Agent 尚未找到可验证联系人。</div>
          </el-tab-pane>

          <el-tab-pane label="研究证据" name="research">
            <template v-if="detail.research">
              <p class="summary-text">{{ detail.research.summary }}</p>
              <div v-if="detail.research.outreach_angles?.length" class="angle-block">
                <h3 class="detail-section-title">建议切入点</h3>
                <div class="tag-list"><el-tag v-for="item in detail.research.outreach_angles" :key="item" type="success" effect="plain">{{ item }}</el-tag></div>
              </div>
              <h3 class="detail-section-title">有来源事实</h3>
              <article v-for="fact in detail.research.facts || []" :key="fact.id" class="evidence-card">
                <p>{{ fact.claim }}</p>
                <div class="evidence-meta">
                  <el-tag size="small" effect="plain">置信度 {{ confidence(fact.confidence) }}</el-tag>
                  <span>采集于 {{ formatTime(fact.captured_at) }}</span>
                  <a :href="fact.source_url" target="_blank" rel="noopener noreferrer">打开来源</a>
                </div>
              </article>
              <div v-if="!detail.research.facts?.length" class="empty-hint">研究完成但没有可引用事实，请要求 Agent 重试。</div>
            </template>
            <div v-else class="empty-hint">Agent 尚未提交企业研究。</div>
          </el-tab-pane>
        </el-tabs>
      </template>
      <template v-if="detail?.status === 'candidate'" #footer>
        <GlassButton
          v-any-permission="['sales_automation:write', 'sales_automation:admin']"
          variant="primary"
          left-icon="Check"
          :loading="approvingId === detail.id"
          @click="approve(detail)"
        >确认进入开发队列</GlassButton>
      </template>
    </DetailDrawer>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import { approveLead, getLead, getLeads } from '@/api/salesAutomation'
import { useListPage } from '@/composables/useListPage'
import { msgSuccess } from '@/utils/feedback'

const leadStatus = value => ({
  candidate: { label: '待确认', type: 'warning' },
  approved: { label: '已确认', type: 'success' },
  rejected: { label: '已拒绝', type: 'info' },
}[value] || { label: value || '-', type: 'info' })
const researchStatus = value => ({
  pending: { label: '待研究', type: 'info' },
  running: { label: '研究中', type: 'warning' },
  completed: { label: '已完成', type: 'success' },
  failed: { label: '失败', type: 'danger' },
}[value] || { label: value || '-', type: 'info' })
const emailStatus = value => ({
  unknown: { label: '未验证', type: 'info' },
  valid: { label: '有效', type: 'success' },
  risky: { label: '有风险', type: 'warning' },
  invalid: { label: '无效', type: 'danger' },
}[value] || { label: value || '-', type: 'info' })
const formatTime = value => value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '-'
const confidence = value => `${Math.round((value || 0) * 100)}%`

const {
  loading, list: leads, total, page, pageSize, searchForm: filters,
  fetchList: fetchLeads, handleSearch: search, handlePageChange, handleSizeChange,
} = useListPage(async params => {
  const clean = Object.fromEntries(Object.entries(params).filter(([, value]) => value !== ''))
  const res = await getLeads(clean)
  return res.data || {}
}, { searchForm: { keyword: '', status: '' } })

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)
const activeTab = ref('company')
const approvingId = ref(null)

async function openDetail(row) {
  detailVisible.value = true
  detailLoading.value = true
  detail.value = null
  activeTab.value = 'company'
  try {
    const res = await getLead(row.id)
    detail.value = res.data
  } finally {
    detailLoading.value = false
  }
}

async function approve(row) {
  approvingId.value = row.id
  try {
    await approveLead(row.id)
    msgSuccess('确认')
    await fetchLeads()
    if (detail.value?.id === row.id) {
      const res = await getLead(row.id)
      detail.value = res.data
    }
  } finally {
    approvingId.value = null
  }
}
</script>

<style scoped>
@import './salesAutomation.css';
.company-cell { display: grid; gap: 3px; }
.lead-filter { width: 260px; }
.company-cell strong { color: var(--text-primary); }
a { color: var(--color-primary); text-decoration: none; }
a:hover { text-decoration: underline; }
.score { color: var(--color-primary); font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.detail-summary { display: flex; align-items: center; justify-content: space-between; gap: 16px; padding: 14px 16px; margin-bottom: 12px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--toolbar-bg); }
.detail-summary h2 { margin: 0 0 4px; color: var(--text-primary); font-size: 18px; }
.score-badge { display: grid; min-width: 70px; text-align: center; }
.score-badge strong { color: var(--color-primary); font-size: 26px; line-height: 1; }
.score-badge span { margin-top: 4px; color: var(--text-muted); font-size: 11px; }
.detail-section-title { margin: 20px 0 10px; color: var(--text-primary); font-size: 14px; }
.tag-list { display: flex; flex-wrap: wrap; gap: 8px; }
.summary-text { margin: 0; color: var(--text-secondary); font-size: 13px; line-height: 1.75; white-space: pre-wrap; }
@media (max-width: 720px) { .lead-filter { width: 100%; } }
</style>
