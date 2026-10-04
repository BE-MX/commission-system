<!--
  培训速递 · 列表页
  标杆：标记/样式照 system/DictManagement.vue，分页/搜索编排照 views/expo/ExpoLeads.vue
-->
<template>
  <div class="page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="training-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div ref="panelRef" class="table-card training-panel">
      <FilterBar  class="toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value" @search="search" @reset="handleReset"><el-input
          v-model="filters.keyword"
          placeholder="搜标题 / 机构 / 讲师 / 总结"
          clearable
          class="filter-w-lg"


        />
<StatusBadge
          v-if="filters.tag"
          closable
          effect="plain"
          type="warning"
          class="tag-filter-chip"
          @close="clearTag"
        >标签：{{ filters.tag }}</StatusBadge><el-checkbox v-model="filters.mine" v-permission="'training:write'" >只看我发布的</el-checkbox>
</FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton
          v-permission="'training:write'"
          variant="primary"
          left-icon="Plus"
          @click="router.push('/training/digests/new')"
        >发布培训速递</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listPageState.hasData.value" :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="listPageState.hasData.value" :data-page="listPageState.dataPage.value" @retry="fetchList" />
<el-table
        :data="list"
        v-loading="loading"
        border
        class="list-table"
        :class="densityClass"
        :max-height="isFullscreen ? undefined : 640"
        @row-click="openDetail" @sort-change="handleSortChange"
      >
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('title')" prop="title" label="培训主题" min-width="240" max-width="380">
          <template #default="{ row }">
            <div class="title-cell">
              <span class="title-text">{{ row.title }}</span>
              <StatusBadge v-if="row.status === 'draft'" size="small" type="info" effect="plain">草稿</StatusBadge>
            </div>
            <div v-if="row.summary" class="summary-text">{{ row.summary }}</div>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('tags')" prop="tags" label="标签" min-width="140" max-width="220">
          <template #default="{ row }">
            <StatusBadge
              v-for="t in row.tags"
              :key="t"
              size="small"
              effect="plain"
              class="row-tag"
              @click.stop="filterByTag(t)"
            >{{ t }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('trained-at')" prop="trained_at" label="培训日期" min-width="110" max-width="130" show-overflow-tooltip />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('org-lecturer')" prop="org_lecturer" label="机构 / 讲师" min-width="150" max-width="220" show-overflow-tooltip>
          <template #default="{ row }">{{ [row.org, row.lecturer].filter(Boolean).join(' / ') || '—' }}</template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('creator')" prop="creator_name" label="参训发布人" min-width="110" max-width="140" show-overflow-tooltip />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('read')" prop="read_minutes" label="阅读" min-width="90" max-width="110">
          <template #default="{ row }">约 {{ row.read_minutes || 1 }} 分钟</template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('feedback')" prop="useful_count" label="反馈" min-width="110" max-width="130">
          <template #default="{ row }">
            <span class="stat-item">👍 {{ row.useful_count }}</span>
            <span class="stat-item muted">阅 {{ row.view_count }}</span>
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="200" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="View" @click.stop="openDetail(row)">查看</GlassButton>
            <GlassButton
              v-if="canEditRow(row)"
              variant="link"
              left-icon="Edit"
              @click.stop="router.push(`/training/digests/${row.id}/edit`)"
            >编辑</GlassButton>
            <GlassButton
              v-if="canDeleteRow(row)"
              variant="link"
              link-tone="danger"
              left-icon="Delete"
              @click.stop="handleDelete(row)"
            >删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        :page-sizes="[20, 50, 100]"
        layout="total, sizes, prev, pager, next"
        class="pager"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { listDigests, deleteDigest } from '@/api/training'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import { confirmDanger, msgSuccess } from '@/utils/feedback'
import { useAuthStore } from '@/stores/auth'
import TableTools from '@/components/TableTools.vue'

const router = useRouter()
const auth = useAuthStore()


// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'title', label: '培训主题' },
  { key: 'tags', label: '标签' },
  { key: 'trained-at', label: '培训日期' },
  { key: 'org-lecturer', label: '机构 / 讲师' },
  { key: 'creator', label: '参训发布人' },
  { key: 'read', label: '阅读' },
  { key: 'feedback', label: '反馈' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('training-list', columnDefs)

function canEditRow(row) {
  return row.created_by === auth.user?.id || auth.hasPermission('training:admin')
}

// 已发布的速递只有管理员能删（与后端 router.delete_digest 同一口径），
// 普通发布人只在草稿阶段可删，避免点了才吃 403
function canDeleteRow(row) {
  if (!canEditRow(row)) return false
  return row.status !== 'published' || auth.hasPermission('training:admin')
}

const listPageState = useListPage(
  async ({ page, page_size, ...form }, { signal, isCurrent }) => {
    const params = { page, page_size }
    if (form.keyword) params.keyword = form.keyword
    if (form.tag) params.tag = form.tag
    if (form.mine) params.mine = true
    const res = await listDigests(params, { signal, suppressToast: true })
    return res.data || {}
  },
  { searchForm: { keyword: '', tag: '', mine: false } },
)
const {
  loading, list, total, page, pageSize, searchForm: filters,
  fetchList, handleSearch: search, handleReset, handlePageChange, handleSizeChange,
} = listPageState

const hasActiveFilters = computed(() => Boolean(filters.keyword || filters.tag || filters.mine))

function resetFilters() {
  handleReset()
}

function openDetail(row) {
  router.push(`/training/digests/${row.id}`)
}

function filterByTag(tag) {
  filters.tag = tag
  search()
}

function clearTag() {
  filters.tag = ''
  search()
}

async function handleDelete(row) {
  try {
    await confirmDanger('删除', row.title)
  } catch {
    return
  }
  await deleteDigest(row.id)
  msgSuccess('删除')
  await listPageState.refreshRemove()
}
function handleSortChange({ prop, order }) { return listPageState.handleSortChange(order ? { sort_field: prop, sort_order: order === 'ascending' ? 'asc' : 'desc' } : {}) }
</script>

<style scoped>
.page {
  padding: 16px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.training-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   会覆盖就地渲染的 el-drawer/el-dialog 的 .el-overlay position: fixed */
.page .training-panel {
  position: relative;
  z-index: 1;
}

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.training-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.training-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：sticky 单元格 + background: inherit，行透明时会透底重影，
   改成磨砂不透明的暖白，表头/hover 态同步（同 invoice-manage.css） */
.training-panel :deep(.el-table-fixed-column--right) {
  background-color: rgba(249, 244, 234, 0.97);
}
.training-panel :deep(th.el-table-fixed-column--right) {
  background-color: rgba(246, 239, 226, 0.98);
}
.training-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) {
  background-color: rgba(245, 236, 220, 0.98);
}

/* 筛选控件三档宽度、操作行、分页均为全局规范类（app.css），本页只保留玻璃皮肤覆写 */
.toolbar {
  background: rgba(255, 255, 255, 0.4);
}

.action-bar {
  background: rgba(255, 255, 255, 0.28);
}

.title-cell {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.title-text {
  font-weight: 600;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.summary-text {
  margin-top: 2px;
  font-size: 12px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-tag {
  margin-right: 4px;
  margin-bottom: 2px;
  cursor: pointer;
}

.tag-filter-chip {
  cursor: default;
}

.stat-item {
  margin-right: 8px;
  font-size: 13px;
}

.stat-item.muted {
  color: var(--text-muted);
}

.list-table :deep(.el-table__row) {
  cursor: pointer;
}
</style>
