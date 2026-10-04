<template>
  <div class="page-wrapper">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="insight-library-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <div class="page-header">
      <div>
        <h1>情报采集库</h1>
        <p>RSS / XPOZ / 竞品监控 / 手工上传的情报条目，支持精选与归档。</p>
      </div>
    </div>

    <!-- 表格卡片：筛选区 + 操作行 + 表格 + 分页（List Page Spec / Action Bar Spec） -->
    <section ref="panelRef" class="table-card library-panel">
      <FilterBar :loading="loading" :pending="listState.hasPendingSearch.value" @search="handleFilterChange" @reset="resetFilter">
        <el-date-picker
          v-model="dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始"
          end-placeholder="结束"
          value-format="YYYY-MM-DD"
          class="filter-w-lg"
        />
        <el-select v-model="filterForm.source_types" multiple collapse-tags placeholder="信源类型" class="filter-w-md">
          <el-option label="RSS" value="google_alerts_rss" />
          <el-option label="XPOZ" value="xpoz" />
          <el-option label="竞品监控" value="competitor_monitor" />
          <el-option label="手工" value="manual" />
        </el-select>
        <el-select v-model="filterForm.credibility_labels" multiple collapse-tags placeholder="可信度" class="filter-w-md">
          <el-option label="已核实" value="verified" />
          <el-option label="可信" value="plausible" />
          <el-option label="存疑" value="uncertain" />
          <el-option label="无法核实" value="unverifiable" />
        </el-select>
        <el-select v-model="filterForm.status" placeholder="状态" class="filter-w-sm">
          <el-option label="活跃" value="active" />
          <el-option label="已归档" value="archived" />
          <el-option label="已标记" value="flagged" />
        </el-select>
        <template #advanced>
        <el-input v-model="filterForm.keyword" placeholder="搜索标题/内容" clearable class="filter-w-md" />
        </template>
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标 -->
      <div class="action-bar">
        <GlassButton variant="primary" :left-icon="Plus" @click="router.push('/insight/sources')" v-if="authStore.hasPermission('insight:admin')">
          添加信源
        </GlassButton>
        <GlassButton variant="secondary" :left-icon="Upload" @click="showUploadDialog = true" v-if="authStore.hasPermission('insight:admin')">
          上传 MD
        </GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading"
          @refresh="loadItems"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="listState.hasData.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="loadItems" />
      <el-table :data="items" v-loading="loading" @selection-change="handleSelectionChange" @sort-change="handleSortChange" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty>
          <ListPageStatus :error="listState.errorMessage.value" :loading="loading" @retry="loadItems">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshLeft" @click="resetFilter">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus>
        </template>
        <el-table-column type="selection" min-width="40" />
        <el-table-column sortable="custom" v-if="visibleKeys.includes('credibility')" label="可信度" min-width="120" prop="credibility_label">
          <template #default="{ row }">
            <StatusBadge :type="credibilityType(row.credibility_label)" size="small">
              {{ credibilityLabel(row.credibility_label) }}
            </StatusBadge>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('title')" label="标题" min-width="300" prop="title">
          <template #default="{ row }">
            <div class="item-title">
              <el-icon v-if="row.is_featured" class="featured-star"><Star-Filled /></el-icon>
              <span>{{ row.title || '(无标题)' }}</span>
            </div>
            <div class="item-meta">
              <StatusBadge size="small" type="info">{{ row.source_type }}</StatusBadge>
              <span>{{ formatDate(row.collected_at) }}</span>
              <span v-if="row.related_competitor">{{ row.related_competitor }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('item-type')" prop="item_type" label="类型" min-width="160">
          <template #default="{ row }">
            <StatusBadge size="small">{{ row.item_type || '-' }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column sortable="custom" v-if="visibleKeys.includes('status')" label="状态" min-width="140" prop="status">
          <template #default="{ row }">
            <StatusBadge :type="statusType(row.status)" size="small">{{ row.status }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="toggleFeature(row)"><el-icon><Close /></el-icon>
              {{ row.is_featured ? '取消精选' : '精选' }}
            </el-button>
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
        @size-change="handleSizeChange"
        @current-change="handlePageChange"
      />
    </section>

    <!-- 批量操作栏 -->
    <div class="batch-bar" v-if="selectedItems.length > 0">
      <span>已选 {{ selectedItems.length }} 项</span>
      <el-button @click="batchFeature(true)">标记精选</el-button>
      <el-button @click="batchArchive">归档</el-button>
    </div>

    <!-- 上传 MD 弹窗 -->
    <el-dialog v-model="showUploadDialog" title="上传 Markdown" width="640px">
      <el-form label-position="top" :model="uploadForm">
        <el-form-item label="标题">
          <el-input v-model="uploadForm.title" placeholder="留空使用文件名" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="uploadForm.tags" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="文件">
          <el-upload
            ref="uploadRef"
            :auto-upload="false"
            :limit="1"
            accept=".md"
            :on-change="handleFileChange"
          >
            <el-button type="primary">选择文件</el-button>
          </el-upload>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showUploadDialog = false">取消</el-button>
        <el-button type="primary" @click="submitUpload" :loading="uploading">上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import ListPageStatus from '@/components/ListPageStatus.vue'
import FilterBar from '@/components/FilterBar.vue'
import { useListPage } from '@/composables/useListPage'
import { msgSuccessText, msgError, msgWarning } from '@/utils/feedback'
import { ref, reactive, computed, toRef } from 'vue'
import { useRouter } from 'vue-router'

import { Plus, RefreshLeft, Search, Upload, StarFilled } from '@element-plus/icons-vue'
import { useAuthStore } from '@/stores/auth'
import { listItems, toggleItemFeature, batchFeature as apiBatchFeature, batchStatus, uploadMd } from '@/api/insight'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { formatBeijingDate } from '@/utils/datetime'

const authStore = useAuthStore()
const router = useRouter()
const libSort = useTableSort()

// 状态
const listState = useListPage(async (params, { signal }) => {
  const { dateRange, sort_field, sort_order, ...query } = params
  if (sort_field) { query.sort_by = sort_field; query.sort_desc = sort_order === 'desc' }
  if (dateRange?.length === 2) { query.start_date = dateRange[0]; query.end_date = dateRange[1] }
  if (query.source_types.length) query.source_types = query.source_types.join(',')
  if (query.credibility_labels.length) query.credibility_labels = query.credibility_labels.join(',')
  return (await listItems(query, { signal, suppressToast: true })).data
}, { searchForm: { dateRange: [], source_types: [], credibility_labels: [], status: '', keyword: '' } })
const { loading, list: items, total, page, pageSize, searchForm: filterForm, fetchList: loadItems, handleSearch: handleFilterChange, handlePageChange, handleSizeChange } = listState
const dateRange = toRef(filterForm, 'dateRange')

const selectedItems = ref([])

// 列显隐元数据（TableTools 列面板数据源，模板列保持静态；多选列固定显示）
const columnDefs = [
  { key: 'credibility', label: '可信度' },
  { key: 'title', label: '标题' },
  { key: 'item-type', label: '类型' },
  { key: 'status', label: '状态' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('intelligence-library', columnDefs)



// 上传
const showUploadDialog = ref(false)
const uploadForm = reactive({ title: '', tags: '' })
const uploadRef = ref(null)
const uploadFile = ref(null)
const uploading = ref(false)

const hasActiveFilters = computed(() => {
  const applied = listState.appliedSearchForm.value
  return !!(applied.dateRange?.length || applied.source_types.length || applied.credibility_labels.length || applied.status || applied.keyword)
})
function resetFilter() {
  libSort.reset()
  return listState.handleReset({ sortParams: libSort.sortParams.value })
}
function handleSortChange(sort) {
  libSort.onSortChange(sort)
  return listState.handleSortChange(libSort.sortParams.value)
}

function handleSelectionChange(selection) {
  selectedItems.value = selection
}

// 精选
async function toggleFeature(row) {
  try {
    await toggleItemFeature(row.id)
    row.is_featured = !row.is_featured
    msgSuccessText('已更新')
  } catch (error) {
    msgError('操作失败', error)
  }
}

async function batchFeature(isFeatured) {
  const ids = selectedItems.value.map(i => i.id)
  try {
    await apiBatchFeature(ids, isFeatured)
    msgSuccessText('批量更新成功')
    await listState.refreshUpdate()
  } catch (error) {
    msgError('批量更新失败', error)
  }
}

async function batchArchive() {
  const ids = selectedItems.value.map(i => i.id)
  try {
    await batchStatus(ids, 'archived')
    msgSuccessText('已归档')
    await listState.refreshRemove()
  } catch (error) {
    msgError('归档失败', error)
  }
}

// 上传
function handleFileChange(file) {
  uploadFile.value = file.raw
}

async function submitUpload() {
  if (!uploadFile.value) {
    msgWarning('请选择文件')
    return
  }
  uploading.value = true
  const formData = new FormData()
  formData.append('file', uploadFile.value)
  if (uploadForm.title) formData.append('title', uploadForm.title)
  if (uploadForm.tags) formData.append('tags', uploadForm.tags)
  try {
    await uploadMd(formData)
    msgSuccessText('上传成功')
    showUploadDialog.value = false
    uploadForm.title = ''
    uploadForm.tags = ''
    uploadFile.value = null
    uploadRef.value?.clearFiles()
    await listState.refreshCreate()
  } catch (error) {
    msgError('上传失败', error)
  } finally {
    uploading.value = false
  }
}

// 辅助
function credibilityType(label) {
  const map = { verified: 'success', plausible: 'warning', uncertain: 'danger', unverifiable: 'info' }
  return map[label] || 'info'
}
function credibilityLabel(label) {
  const map = { verified: '已核实', plausible: '可信', uncertain: '存疑', unverifiable: '无法核实' }
  return map[label] || label
}
function statusType(status) {
  const map = { active: 'success', archived: 'info', flagged: 'warning' }
  return map[status] || 'info'
}
function formatDate(dt) {
  return formatBeijingDate(dt)
}


</script>

<style scoped>
.page-wrapper {
  padding: 24px;
  /* 极光层（.lg-aurora，与工作台同源）定位上下文 */
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台/发票页） */
.insight-library-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   会覆盖就地渲染的 el-dialog 的 .el-overlay position: fixed。
   .batch-bar 本身是 position: fixed + z-index:100，天然在极光之上，不列入 */
.page-wrapper .page-header,
.page-wrapper .library-panel {
  position: relative;
  z-index: 1;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-header h1 {
  font-size: 20px;
  font-weight: 600;
  margin: 0;
}
.page-header p {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--text-secondary);
}
/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 白底）；
   筛选区/操作行/分页均为全局规范类（app.css .table-card > …），本页不覆写 */
.library-panel {
  margin-bottom: 16px;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
  overflow: hidden;
}

/* 全屏态：面板自身滚动（.table-card 默认 overflow:hidden） */
.library-panel:fullscreen {
  overflow: auto;
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.library-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：sticky 单元格 + background: inherit，行透明时会透底重影，
   改成磨砂不透明的暖白，表头/hover 态同步（同 invoice-manage.css） */
.library-panel :deep(.el-table-fixed-column--right) {
  background-color: rgba(249, 244, 234, 0.97);
}
.library-panel :deep(th.el-table-fixed-column--right) {
  background-color: rgba(246, 239, 226, 0.98);
}
.library-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) {
  background-color: rgba(245, 236, 220, 0.98);
}
.item-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 500;
}
.featured-star {
  color: var(--warning);
  font-size: 14px;
}
.item-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-secondary);
  display: flex;
  gap: 8px;
  align-items: center;
}
.batch-bar {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  background: #fff;
  padding: 12px 24px;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.15);
  display: flex;
  align-items: center;
  gap: 12px;
  z-index: 100;
}
</style>
