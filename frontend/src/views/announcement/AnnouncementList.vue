<template>
  <div class="announcement-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="announcement-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <div>
        <h2>公告管理</h2>
        <p>发布通知、沉淀知识，重要信息及时送达。</p>
      </div>
    </div>

    <el-alert v-if="!config.initialized" class="page-alert" type="info" title="公告库尚未初始化，请管理员在公告设置中创建。" :closable="false" show-icon />
    <section v-else ref="panelRef" class="table-card announcement-panel">
      <FilterBar  class="toolbar" :loading="listPageState.loading.value" :pending="listPageState.hasPendingSearch.value" @search="search" @reset="reset"><el-input v-model="searchForm.q" clearable placeholder="搜索标题或正文" class="filter-w-lg"  >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
<el-select v-model="searchForm.category_id" clearable placeholder="全部类别" class="filter-w-sm">
          <el-option v-for="c in categories" :key="c.id" :label="c.title" :value="c.id" />
        </el-select>
<el-select v-model="searchForm.status" clearable placeholder="全部状态" class="filter-w-sm">
          <el-option v-for="(label, value) in statuses" :key="value" :label="label" :value="value" />
        </el-select>
</FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-any-permission="['announcement:write', 'announcement:admin']" variant="primary" left-icon="Plus" :disabled="!config.initialized" @click="openEditor(null, true)">新建公告</GlassButton>
        <GlassButton variant="secondary" left-icon="Calendar" :disabled="!config.initialized" @click="weeklyOpen = true">公告周报</GlassButton>
        <GlassButton v-permission="'announcement:admin'" variant="secondary" left-icon="Setting" @click="settingsOpen = true">公告设置</GlassButton>
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
<el-table @sort-change="event => listPageState.handleSortChange(tableSortParams(event))" v-loading="loading" :data="list" class="list-table" :class="densityClass" border :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="listPageState.errorMessage.value" :loading="listPageState.loading.value" :has-data="false" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="reset">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column sortable="custom" prop="title" v-if="visibleKeys.includes('title')" label="公告标题" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">
            <el-button link type="primary" @click="openEditor(row.id)"><el-icon><Document /></el-icon>{{ row.title }}</el-button>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" prop="flags" v-if="visibleKeys.includes('flags')" label="标记" min-width="130">
          <template #default="{ row }">
            <StatusBadge v-if="row.pinned" size="small" effect="plain">置顶</StatusBadge>
            <StatusBadge v-if="row.important" size="small" effect="plain" type="warning">重要</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('category')" prop="category_name" label="类别" min-width="130" show-overflow-tooltip />
        <el-table-column sortable="custom" prop="published_at" v-if="visibleKeys.includes('published-at')" label="发布时间" min-width="180">
          <template #default="{ row }">{{ formatBeijingDateTime(row.published_at) }}</template>
        </el-table-column>
        <el-table-column sortable="custom" prop="expires_at" v-if="visibleKeys.includes('expires-at')" label="截止时间" min-width="180">
          <template #default="{ row }">{{ formatBeijingDateTime(row.expires_at) }}</template>
        </el-table-column>
        <el-table-column sortable="custom" prop="status" v-if="visibleKeys.includes('status')" label="发布状态" min-width="120">
          <template #default="{ row }">
            <StatusBadge size="small" effect="plain">{{ statuses[row.status] || row.status }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" prop="delivery" v-if="visibleKeys.includes('delivery')" label="群推送" min-width="135">
          <template #default="{ row }">{{ deliveryLabel(row.deliveries) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="260" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <div class="table-actions">
              <GlassButton variant="link" left-icon="View" @click="openEditor(row.id)">查看</GlassButton>
              <GlassButton v-if="row.status !== 'withdrawn'" v-any-permission="['announcement:write', 'announcement:admin', 'knowledge:review']" variant="link" left-icon="Edit" @click="openEditor(row.id, true)">{{ row.pending_approval_id ? '审核详情' : '编辑' }}</GlassButton>
              <GlassButton v-permission="'announcement:admin'" variant="link" left-icon="Top" @click="pin(row)">{{ row.pinned ? '取消置顶' : '置顶' }}</GlassButton>
              <GlassButton v-if="row.published_at && row.status !== 'withdrawn'" v-permission="'announcement:admin'" variant="link" link-tone="danger" left-icon="Remove" @click="withdraw(row)">撤回</GlassButton>
              <GlassButton v-if="row.status === 'draft' && !row.published_at" v-any-permission="['announcement:write', 'announcement:admin']" variant="link" link-tone="danger" left-icon="Delete" @click="remove(row)">删除</GlassButton>
            </div>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination
        v-model:current-page="page" v-model:page-size="pageSize" :total="total"
        :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
        class="pager" @current-change="handlePageChange" @size-change="handleSizeChange"
      />
    </section>

    <DetailDrawer :model-value="editorOpen" :title="editing ? '编辑与审核公告' : '公告详情'" width="760px" @update:model-value="closeEditor">
      <AnnouncementEditor v-if="editorOpen" ref="editor" :key="editorKey" :document-id="selectedId" :edit="editing" :config="config" :categories="categories" @saved="handleSaved" />
    </DetailDrawer>
    <DetailDrawer v-model="settingsOpen" title="公告设置" width="760px" destroy-on-close><AnnouncementSettings @updated="load" /></DetailDrawer>
    <DetailDrawer v-model="weeklyOpen" title="公告周报" width="760px" destroy-on-close><AnnouncementWeekly /></DetailDrawer>
  </div>
</template>

<script setup>
import { tableSortParams } from "@/utils/tableSort"
import { confirmAction, promptAction, confirmDanger, msgSuccess } from '@/utils/feedback'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'

import { Document, Search } from '@element-plus/icons-vue'
import { announcementApi as api } from '@/api/announcement'
import { useListPage } from '@/composables/useListPage'
import { useTableView } from '@/composables/useTableView'
import { formatBeijingDateTime } from '@/utils/datetime'
import DetailDrawer from '@/components/DetailDrawer.vue'
import TableTools from '@/components/TableTools.vue'
import AnnouncementEditor from './AnnouncementEditor.vue'
import AnnouncementSettings from './AnnouncementSettings.vue'
import AnnouncementWeekly from './AnnouncementWeekly.vue'
import { deliveryLabel } from './presentation.js'

const route = useRoute(), router = useRouter()
const config = ref({ initialized: false }), categories = ref([])
const settingsOpen = ref(false), weeklyOpen = ref(false), editorOpen = ref(false), editing = ref(false)
const selectedId = ref(null), editorKey = ref(0), editor = ref(null)
const statuses = { draft: '草稿', pending: '待审核', published: '已发布', withdrawn: '已撤回' }
// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'title', label: '公告标题' },
  { key: 'flags', label: '标记' },
  { key: 'category', label: '类别' },
  { key: 'published-at', label: '发布时间' },
  { key: 'expires-at', label: '截止时间' },
  { key: 'status', label: '发布状态' },
  { key: 'delivery', label: '群推送' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('announcement-list', columnDefs)
const listPageState = useListPage(
  (params, { signal, isCurrent }) => api.get('', Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== null)), { signal, suppressToast: true }),
  { immediate: false, searchForm: { q: '', category_id: null, status: '' } },
)
const { list, loading, total, page, pageSize, searchForm, fetchList, handleSearch: search, handleReset: reset, handlePageChange, handleSizeChange } = listPageState
const hasActiveFilters = computed(() => Boolean(searchForm.q || searchForm.category_id || searchForm.status))
function handleSaved({ created = false } = {}) { return created ? listPageState.refreshCreate() : listPageState.refreshUpdate() }
async function load() {
  config.value = await api.get('/config')
  if (config.value.initialized) { categories.value = await api.get('/categories'); await fetchList() }
}
function openEditor(id, edit = false) { selectedId.value = id; editing.value = edit; editorKey.value++; editorOpen.value = true }
async function mayLeave() {
  if (!editor.value?.hasChanges) return true
  try { await confirmAction('草稿尚未保存，离开会丢失修改。', '未保存的修改', { confirmButtonText: '放弃修改', cancelButtonText: '继续编辑' }); return true }
  catch { return false }
}
async function closeEditor(value) {
  if (value || !(await mayLeave())) return
  editorOpen.value = false
  if (route.params.documentId) router.replace('/announcements')
}
async function pin(row) { await api.put(`/${row.id}/pin`, { pinned: !row.pinned }); await listPageState.refreshUpdate() }
async function withdraw(row) {
  let reason
  try { reason = (await promptAction('撤回后将停止展示，并向公告群发送撤回说明。请填写原因。', '撤回公告', { inputPattern: /\S+/, inputErrorMessage: '请填写原因' })).value }
  catch { return }
  await api.post(`/${row.id}/withdraw`, { reason }); await listPageState.refreshUpdate(); msgSuccess('撤回')
}
async function remove(row) { try { await confirmDanger('删除', row.title) } catch { return }; await api.delete(`/${row.id}`); await listPageState.refreshRemove(); msgSuccess('删除') }
function beforeUnload(event) { if (editor.value?.hasChanges) { event.preventDefault(); event.returnValue = '' } }
onBeforeRouteLeave(mayLeave)
onMounted(async () => { window.addEventListener('beforeunload', beforeUnload); await load(); if (route.params.documentId) openEditor(route.params.documentId) })
onBeforeUnmount(() => window.removeEventListener('beforeunload', beforeUnload))
</script>

<style scoped>
.announcement-page { position: relative; }
.announcement-aurora { inset: -24px -28px; }
/* 内容压到极光之上。点名内容块，不用 > :not(.lg-aurora) 通配——
   通配会覆盖就地渲染抽屉的 .el-overlay position: fixed（DESIGN.md 红线） */
.announcement-page .page-header,
.announcement-page .page-alert,
.announcement-page .announcement-panel { position: relative; z-index: 1; }

.page-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; flex-wrap: wrap; margin-bottom: 16px; }
.page-header h2 { margin: 0 0 6px; font-family: var(--font-display); font-size: 17px; font-weight: 700; color: var(--text-primary); }
.page-header p { margin: 0; font-size: 14px; font-weight: 500; color: var(--text-secondary); }

.page-alert { margin-bottom: 14px; }

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.announcement-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 筛选控件三档宽度、操作行、分页均为全局规范类（app.css），本页只保留玻璃皮肤覆写 */
.toolbar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 14px; border-bottom: 1px solid var(--border-color); border-radius: var(--dash-card-radius) var(--dash-card-radius) 0 0; background: rgba(255, 255, 255, 0.4); }
.action-bar { background: rgba(255, 255, 255, 0.28); }

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.announcement-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列磨砂不透明（Element 2.13 sticky 单元格 background: inherit 会透影，DESIGN.md） */
.announcement-panel :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.announcement-panel :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.announcement-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }
</style>
