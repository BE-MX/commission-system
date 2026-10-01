<template>
  <div class="change-log-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="changelog-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <h2>数据治理 · 变更历史</h2>
    </div>

    <FilterBar :loading="loading" :pending="listState.hasPendingSearch.value" @search="searchLogs" @reset="resetFilters">
      <el-input v-model="filters.concept_id" placeholder="概念ID" clearable class="filter-w-md" />
      <el-select v-model="filters.action" placeholder="操作类型" clearable class="filter-w-sm">
        <el-option v-for="a in actionOptions" :key="a.value" :label="a.label" :value="a.value" />
      </el-select>
    </FilterBar>

    <ListPageStatus :error="listState.errorMessage.value" :loading="loading" :has-data="listState.hasData.value" :data-page="listState.dataPage.value" @retry="loadLogs" />
    <el-empty v-if="listState.isEmpty.value" description="暂无变更记录" />
    <el-timeline v-loading="loading" class="log-timeline">
      <el-timeline-item v-for="log in logs" :key="log.id"
        :timestamp="formatDate(log.timestamp)" placement="top"
        :type="actionColor(log.action)">
        <el-card shadow="never" class="log-card lg-card">
          <div class="log-header">
            <StatusBadge :type="actionTagType(log.action)" size="small">{{ actionLabels[log.action] }}</StatusBadge>
            <span v-if="log.concept_name_zh" class="log-concept">
              <router-link :to="`/governance/concepts/${log.concept_id}`">
                {{ log.concept_name_zh }}
              </router-link>
            </span>
            <span class="log-operator">操作人: {{ log.operator || '-' }}</span>
          </div>
          <div v-if="log.comment" class="log-comment">{{ log.comment }}</div>
          <div v-if="log.changed_fields?.length" class="log-changes">
            <div v-for="(c, i) in log.changed_fields" :key="i" class="change-item">
              <span class="change-field">{{ fieldLabels[c.field] || c.field }}</span>
              <span class="change-before">{{ formatVal(c.before) }}</span>
              <span class="change-arrow">→</span>
              <span class="change-after">{{ formatVal(c.after) }}</span>
            </div>
          </div>
          <div class="log-actions">
            <el-button v-if="isAdmin" type="primary" link @click="handleRollback(log)">
              回滚到此版本
            </el-button>
          </div>
        </el-card>
      </el-timeline-item>
    </el-timeline>

    <div class="pagination-wrap">
      <el-pagination class="pager" :page-sizes="[20, 50, 100]" v-model:current-page="page" v-model:page-size="pageSize"
        :total="total" layout="total, sizes, prev, pager, next" @size-change="handleSizeChange" @current-change="handlePageChange" />
    </div>
  </div>
</template>

<script setup>
import ListPageStatus from '@/components/ListPageStatus.vue'
import FilterBar from '@/components/FilterBar.vue'
import { useListPage } from '@/composables/useListPage'
import { msgError, confirmAction, msgSuccessText } from '@/utils/feedback'
import { ref, reactive, computed, onMounted } from 'vue'

import { Search } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { listChangeLogs, rollbackToVersion } from '@/api/governance'
import { formatBeijingDateTime } from '@/utils/datetime'

const authStore = useAuthStore()
const isAdmin = computed(() => authStore.hasAnyPermission(['governance:admin']))

const actionLabels = {
  create: '创建', edit: '编辑', submit: '提交审批',
  approve: '审批通过', reject: '驳回', deprecate: '废弃', rollback: '回滚',
}
const actionOptions = Object.entries(actionLabels).map(([v, l]) => ({ value: v, label: l }))

const actionTagType = (a) => ({
  create: 'success', edit: '', submit: 'warning',
  approve: 'success', reject: 'danger', deprecate: 'info', rollback: 'warning',
}[a] || 'info')

const actionColor = (a) => ({
  create: 'success', approve: 'success', reject: 'danger', deprecate: 'info', rollback: 'warning',
}[a] || 'primary')

const fieldLabels = {
  status: '状态', name_zh: '中文名', name_en: '英文名',
  one_liner: '一句话定义', full_definition: '完整定义',
  boundary_includes: '包含范围', boundary_excludes: '排除范围',
}

const listState = useListPage(async (params, { signal }) => (await listChangeLogs(params, { signal, suppressToast: true })).data,
  { searchForm: { concept_id: '', action: '' } })
const { list: logs, loading, total, page, pageSize, searchForm: filters, fetchList: loadLogs, handleSearch: searchLogs, handleReset: resetFilters, handlePageChange, handleSizeChange } = listState

async function handleRollback(log) {
  try {
    await confirmAction(`确认回滚到 ${formatDate(log.timestamp)} 的版本？`, '回滚确认')
    await rollbackToVersion(log.id)
    msgSuccessText('已回滚')
    await listState.refreshUpdate()
  } catch { /* cancel */ }
}

function formatDate(dt) {
  return formatBeijingDateTime(dt)
}

function formatVal(v) {
  if (v === null || v === undefined) return '-'
  if (Array.isArray(v)) return v.join(', ')
  return String(v)
}


</script>

<style scoped>
.change-log-page {
  padding: 20px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.changelog-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。必须点名内容块，不能用 > :not(.lg-aurora) 通配 */
.change-log-page .page-header,
.change-log-page .filter-bar,
.change-log-page .log-timeline,
.change-log-page .pagination-wrap {
  position: relative;
  z-index: 1;
}

.page-header {
  margin-bottom: 20px;
}

.page-header h2 {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.filter-bar {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

/* 玻璃质感由 .lg-card 提供，这里只留布局 */
.log-card {
  margin-bottom: 0;
}

.log-header {
  display: flex;
  align-items: center;
  gap: 12px;
}

.log-concept a {
  color: var(--el-color-primary);
  text-decoration: none;
  font-weight: 500;
}

.log-operator {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.log-comment {
  margin-top: 8px;
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.log-changes {
  margin-top: 8px;
}

.change-item {
  font-size: 13px;
  margin: 4px 0;
}

.change-field {
  font-weight: 500;
  color: var(--el-text-color-primary);
}

.change-before {
  color: var(--el-color-danger);
  text-decoration: line-through;
  margin: 0 4px;
}

.change-arrow {
  color: var(--el-text-color-secondary);
  margin: 0 4px;
}

.change-after {
  color: var(--el-color-success);
  font-weight: 500;
}

.log-actions {
  margin-top: 8px;
  text-align: right;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
