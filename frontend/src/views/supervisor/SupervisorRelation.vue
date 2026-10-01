<template>
  <div class="supervisor-rel-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="supervisor-rel-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 表格卡片：筛选区 + 操作行 + 表格 + 分页（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="search" @reset="resetFilters">
        <el-input v-model="keyword" placeholder="搜索业务员姓名/ID" clearable class="filter-w-md">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </FilterBar>

      <div class="action-bar">
        <GlassButton v-permission="'supervisor:write'" variant="primary" left-icon="Upload" @click="importDialogVisible = true">批量导入</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading" @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="hasData && errorMessage" :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table :data="tableData" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" @sort-change="changeSort">
        <template #empty><ListPageStatus :error="errorMessage" :loading="loading" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
        </ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('salesperson-id')" prop="salesperson_id" label="业务员ID" min-width="200" max-width="300" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('salesperson-name')" prop="salesperson_name" label="业务员姓名" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('supervisor-id')" prop="supervisor_id" label="一级主管ID" min-width="200" max-width="300" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('supervisor-name')" prop="supervisor_name" label="一级主管姓名" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
        <el-table-column v-if="visibleKeys.includes('second-supervisor-id')" prop="second_supervisor_id" label="二级主管ID" min-width="200" max-width="300" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('second-supervisor-name')" prop="second_supervisor_name" label="二级主管姓名" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('effective-start')" prop="effective_start" label="生效日期" min-width="120" max-width="180" show-overflow-tooltip sortable="custom" />
        <el-table-column class-name="table-action-column" label="操作" min-width="160" max-width="240">
          <template #default="{ row }">
            <GlassButton v-permission="'supervisor:write'" variant="link" left-icon="Edit" @click="openSetDialog(row)">变更主管</GlassButton>
            <GlassButton variant="link" left-icon="Clock" @click="openHistory(row)">查看历史</GlassButton>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        class="pager"
        v-model:current-page="page"
        v-model:page-size="pageSize"
        :total="total"
        layout="total, sizes, prev, pager, next"
        :page-sizes="[20, 50, 100]"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>

    <!-- 变更主管 Dialog -->
    <el-dialog v-model="setDialogVisible" title="变更主管" width="480px">
      <el-form label-position="top">
        <el-form-item label="业务员">
          <span>{{ currentRow?.salesperson_name || currentRow?.salesperson_id }}</span>
        </el-form-item>
        <el-form-item label="一级主管ID">
          <el-input v-model="relForm.supervisor_id" placeholder="输入一级主管员工ID" />
        </el-form-item>
        <el-form-item label="二级主管ID">
          <el-input v-model="relForm.second_supervisor_id" placeholder="输入二级主管员工ID（可选）" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="setDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitRelation">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- 历史 Drawer -->
    <DetailDrawer v-model="historyVisible" :title="`${historyRow?.salesperson_name || ''} 主管变更历史`" width="640px">
      <ListPageStatus :paged="false" :error="historyResource.errorMessage.value" :loading="historyResource.loading.value" :has-data="historyResource.hasLoaded.value" @retry="fetchHistory" />
      <el-timeline v-if="historyList.length">
        <el-timeline-item
          v-for="item in historyList"
          :key="item.id"
          :timestamp="item.effective_start"
          placement="top"
        >
          <el-card shadow="never" body-style="padding: 12px">
            <div>一级主管：{{ item.supervisor_id }}</div>
            <div v-if="item.second_supervisor_id">二级主管：{{ item.second_supervisor_id }}</div>
            <span v-if="item.effective_end" class="history-range">截至 {{ item.effective_end }}</span>
            <StatusBadge v-if="item.is_current" type="primary" size="small" style="margin-left:8px">当前</StatusBadge>
          </el-card>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else-if="historyResource.isEmpty.value" description="暂无历史记录" />
    </DetailDrawer>

    <!-- 批量导入 Dialog -->
    <el-dialog v-model="importDialogVisible" title="批量导入主管关系" width="480px">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        Excel 模板列：业务员ID(user_id) | 一级主管ID(user_id) | 二级主管ID(user_id, 可选)
      </el-alert>
      <el-upload
        ref="uploadRef"
        drag
        :auto-upload="false"
        :limit="1"
        accept=".xlsx,.xls"
        :on-change="handleFileChange"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽或 <em>点击上传</em></div>
      </el-upload>
      <div v-if="importResult" style="margin-top:16px">
        <ResponsiveDescriptions :column="3" border size="small">
          <el-descriptions-item label="总行数">{{ importResult.total_rows }}</el-descriptions-item>
          <el-descriptions-item label="成功">{{ importResult.success }}</el-descriptions-item>
          <el-descriptions-item label="失败">{{ importResult.failed }}</el-descriptions-item>
        </ResponsiveDescriptions>
        <div v-if="importResult.failures?.length" style="margin-top:8px">
          <el-text type="danger" v-for="f in importResult.failures" :key="f" tag="div" size="small">{{ f }}</el-text>
        </div>
      </div>
      <template #footer>
        <GlassButton variant="ghost" @click="importDialogVisible = false">关闭</GlassButton>
        <GlassButton variant="primary" :loading="importing" @click="submitImport" :disabled="!importFile">
          开始导入
        </GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { useListPage } from '@/composables/useListPage'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { toRef } from 'vue'
import { msgWarning, msgSuccessText } from '@/utils/feedback'
import { computed, onMounted, ref, watch } from 'vue'

import { Search } from '@element-plus/icons-vue'
import TableTools from '@/components/TableTools.vue'
import { useTableView } from '@/composables/useTableView'
import { useTableSort } from '@/composables/useTableSort'
import { getSupervisorList, setSupervisorRelation, getSupervisorHistory, importSupervisorRelations } from '@/api/supervisor'

const orderSort = useTableSort()

const listState = useListPage(async (params, { signal }) => {
  const response = await getSupervisorList(params, { signal, suppressToast: true })
  return { items: response.data.items || [], total: response.data.total || 0 }
}, { searchForm: { keyword: '' } })
const { loading, list: tableData, total, page, pageSize, searchForm, appliedSearchForm, errorMessage, hasData, dataPage, hasPendingSearch, fetchList, handleSearch, handleReset: resetFilters, handlePageChange, handleSizeChange, refreshCreate, refreshUpdate, refreshRemove } = listState
const keyword = toRef(searchForm, 'keyword')
const search = handleSearch
function changeSort(event) { orderSort.onSortChange(event); return listState.handleSortChange(orderSort.sortParams.value) }

// 列配置数组：TableTools 列显隐的数据源（List Page Spec 第 9 节，操作列不进配置）
const columnDefs = [
  { key: 'salesperson-id', label: '业务员ID' },
  { key: 'salesperson-name', label: '业务员姓名' },
  { key: 'supervisor-id', label: '一级主管ID' },
  { key: 'supervisor-name', label: '一级主管姓名' },
  { key: 'second-supervisor-id', label: '二级主管ID' },
  { key: 'second-supervisor-name', label: '二级主管姓名' },
  { key: 'effective-start', label: '生效日期' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('supervisor-relation', columnDefs)

const hasActiveFilters = computed(() => Boolean(appliedSearchForm.value.keyword))


// 变更主管
const setDialogVisible = ref(false)
const currentRow = ref(null)
const relForm = ref({ supervisor_id: '', second_supervisor_id: '' })
const saving = ref(false)

function openSetDialog(row) {
  currentRow.value = row
  relForm.value = { supervisor_id: '', second_supervisor_id: '' }
  setDialogVisible.value = true
}

async function submitRelation() {
  if (!relForm.value.supervisor_id) {
    msgWarning('请输入一级主管ID')
    return
  }
  saving.value = true
  try {
    const payload = {
      salesperson_id: currentRow.value.salesperson_id,
      supervisor_id: relForm.value.supervisor_id,
    }
    if (relForm.value.second_supervisor_id) {
      payload.second_supervisor_id = relForm.value.second_supervisor_id
    }
    await setSupervisorRelation(payload)
    msgSuccessText('设置成功')
    setDialogVisible.value = false
    refreshUpdate()
  } finally {
    saving.value = false
  }
}

// 查看历史
const historyVisible = ref(false)
const historyRow = ref(null)
const historyResource = useAsyncResource(async (salespersonId, { signal }) => {
  const response = await getSupervisorHistory({ salesperson_id: salespersonId }, { signal, suppressToast: true })
  return response.data || []
}, { initialData: [] })
const historyList = historyResource.data

function openHistory(row) {
  if (historyRow.value?.salesperson_id !== row.salesperson_id) historyResource.clear()
  historyRow.value = row
  historyVisible.value = true
  return fetchHistory()
}
function fetchHistory() {
  if (!historyVisible.value || !historyRow.value) return Promise.resolve(false)
  return historyResource.load(historyRow.value.salesperson_id)
}
watch(historyVisible, visible => {
  if (!visible) { historyResource.clear(); historyRow.value = null }
}, { flush: 'sync' })

// 批量导入
const importDialogVisible = ref(false)
const importFile = ref(null)
const importResult = ref(null)
const importing = ref(false)
const uploadRef = ref()

function handleFileChange(file) {
  importFile.value = file.raw
}

async function submitImport() {
  if (!importFile.value) return
  importing.value = true
  importResult.value = null
  try {
    const res = await importSupervisorRelations(importFile.value)
    importResult.value = res.data
    msgSuccessText(`导入完成：成功 ${res.data.success} 条`)
    refreshUpdate()
  } finally {
    importing.value = false
  }
}


</script>

<style scoped>
.supervisor-rel-page { position: relative; }

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.supervisor-rel-aurora { inset: -24px -28px; }

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   el-drawer/el-dialog 默认就地渲染（append-to-body=false），通配会覆盖
   .el-overlay 的 position: fixed，抽屉/弹窗打开后看不见 */
.supervisor-rel-page .toolbar,
.supervisor-rel-page .table-card,
.supervisor-rel-page .pagination {
  position: relative;
  z-index: 1;
}

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 白底） */
.supervisor-rel-page .table-card {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.supervisor-rel-page .table-card :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
.history-range { color: var(--text-muted); font-size: 12px; margin-left: 4px; }
</style>
