<template>
  <div class="process-manage">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="process-manage-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 表格卡片：筛选区 + 操作行 + 表格 + 分页（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="search" @reset="resetFilters">
        <el-input v-model="searchName" placeholder="搜索工序名称" clearable class="filter-w-md">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filterStatus" placeholder="状态" clearable class="filter-w-sm">
          <el-option label="启用" :value="1" />
          <el-option label="禁用" :value="0" />
        </el-select>
      </FilterBar>

      <!-- 操作行：主操作按钮组 + TableTools 四图标 -->
      <div class="action-bar">
        <GlassButton variant="primary" :left-icon="Plus" @click="openForm()">新增工序</GlassButton>
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
      <el-table :data="items" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty>
          <ListPageStatus :error="errorMessage" :loading="loading" @retry="fetchList">
          <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
            <GlassButton v-if="hasActiveFilters" :left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
          </el-empty>
          </ListPageStatus>
        </template>
        <el-table-column v-if="visibleKeys.includes('id')" prop="id" label="ID" min-width="70" max-width="100" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="工序名称" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('description')" prop="description" label="描述" min-width="200" max-width="300" show-overflow-tooltip />
        <el-table-column v-if="visibleKeys.includes('sort-order')" prop="sort_order" label="排序" min-width="80" max-width="120" />
        <el-table-column v-if="visibleKeys.includes('customer-track')" label="客户进度页" min-width="110" max-width="140">
          <template #default="{ row }">
            <StatusBadge :type="row.show_in_domestic_track ? 'success' : 'info'" size="small" effect="plain">
              {{ row.show_in_domestic_track ? '显示' : '隐藏' }}
            </StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="100" max-width="120">
          <template #default="{ row }">
            <StatusBadge :type="row.status === 1 ? 'success' : 'info'" size="small" effect="plain">
              {{ row.status === 1 ? '启用' : '禁用' }}
            </StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('created-at')" label="创建时间" min-width="160" max-width="240">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column class-name="table-action-column" label="操作" min-width="240" max-width="360" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="Edit" @click="openForm(row)">编辑</GlassButton>
            <GlassButton variant="link" :link-tone="row.status === 1 ? 'warning' : 'success'" left-icon="SwitchButton" @click="toggleStatus(row)">
              {{ row.status === 1 ? '禁用' : '启用' }}
            </GlassButton>
            <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
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
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑工序' : '新增工序'" width="480px" destroy-on-close>
      <el-form label-position="top" ref="formRef" :model="form" :rules="formRules">
        <el-form-item label="工序名称" prop="name">
          <el-input v-model="form.name" maxlength="100" placeholder="2-100字" />
        </el-form-item>
        <el-form-item label="工序描述" prop="description">
          <el-input v-model="form.description" type="textarea" :rows="3" maxlength="500" placeholder="可选" />
        </el-form-item>
        <el-form-item label="排序权重">
          <el-input-number v-model="form.sort_order" :min="0" :step="1" />
        </el-form-item>
        <el-form-item label="客户可见">
          <el-switch v-model="form.show_in_domestic_track" :active-value="1" :inactive-value="0" active-text="进度码页显示" inactive-text="隐藏" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="formVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确认</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { useListPage } from '@/composables/useListPage'
import { msgSuccessText, msgError, confirmAction } from '@/utils/feedback'
import { ref, computed, toRef, onMounted } from 'vue'

import { Plus, RefreshLeft, Search } from '@element-plus/icons-vue'
import * as api from '@/api/production'
import { formatBeijingDateTime } from '@/utils/datetime'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'

const listState = useListPage(async (params, { signal }) => {
  const response = await api.getProcesses({ ...params, name: params.name || undefined, status: params.status ?? undefined }, { signal, suppressToast: true })
  return { items: response.items || [], total: response.total || 0 }
}, { searchForm: { name: '', status: null } })
const { loading, list: items, total, page, pageSize, searchForm, appliedSearchForm, hasPendingSearch, errorMessage, hasData, dataPage, fetchList, handleSearch: search, handleReset: resetFilters, handlePageChange, handleSizeChange, refreshCreate, refreshUpdate, refreshRemove } = listState
const loadData = refreshUpdate
const searchName = toRef(searchForm, 'name')
const filterStatus = toRef(searchForm, 'status')

// 列显隐元数据（TableTools 列面板数据源，模板列保持静态）
const columnDefs = [
  { key: 'id', label: 'ID' },
  { key: 'name', label: '工序名称' },
  { key: 'description', label: '描述' },
  { key: 'sort-order', label: '排序' },
  { key: 'customer-track', label: '客户进度页' },
  { key: 'status', label: '状态' },
  { key: 'created-at', label: '创建时间' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('process-manage', columnDefs)

const hasActiveFilters = computed(() => Boolean(appliedSearchForm.value.name) || appliedSearchForm.value.status !== null)




const formVisible = ref(false)
const submitting = ref(false)
const form = ref({ name: '', description: '', sort_order: 0, show_in_domestic_track: 1 })
const formRef = ref(null)
const formRules = {
  name: [{ required: true, message: '请输入工序名称', trigger: 'blur' }, { min: 2, max: 100, message: '2-100字', trigger: 'blur' }],
}

function formatTime(dt) {
  return formatBeijingDateTime(dt, { seconds: false, fallback: '' })
}


function openForm(row) {
  if (row) {
    form.value = {
      id: row.id, name: row.name, description: row.description || '', sort_order: row.sort_order,
      show_in_domestic_track: row.show_in_domestic_track ?? 1,
    }
  } else {
    form.value = { name: '', description: '', sort_order: 0, show_in_domestic_track: 1 }
  }
  formVisible.value = true
}

async function handleSubmit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    if (form.value.id) {
      await api.updateProcess(form.value.id, form.value)
    } else {
      await api.createProcess(form.value)
    }
    msgSuccessText(form.value.id ? '已更新' : '已创建')
    formVisible.value = false
    await (form.value.id ? refreshUpdate() : refreshCreate())
  } catch (e) {
    msgError(e.response?.data?.detail || '操作失败', e)
  } finally {
    submitting.value = false
  }
}

async function toggleStatus(row) {
  const newStatus = row.status === 1 ? 0 : 1
  const label = newStatus === 0 ? '禁用' : '启用'
  try {
    await api.updateProcess(row.id, { status: newStatus })
    msgSuccessText(`已${label}`)
    loadData()
  } catch (e) {
    msgError(e.response?.data?.detail || '操作失败', e)
  }
}

async function handleDelete(row) {
  try {
    await confirmAction('删除后不可恢复，确认删除？', '提示', { type: 'warning' })
    await api.deleteProcess(row.id)
    msgSuccessText('已删除')
    await refreshRemove()
  } catch (e) {
    if (e !== 'cancel') msgError(e.response?.data?.detail || '删除失败', e)
  }
}


</script>

<style scoped>
.process-manage { padding: 20px; position: relative; }

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.process-manage-aurora { inset: -24px -28px; }

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   el-dialog 默认就地渲染（append-to-body=false），通配会覆盖
   .el-overlay 的 position: fixed，弹窗打开后看不见。
   同时覆写全局 .table-card 白底为同款渐变玻璃 */
.process-manage .table-card {
  position: relative;
  z-index: 1;
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 筛选区/操作行/分页均为全局规范类（app.css .table-card > …），本页不覆写 */

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.process-manage .table-card :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：sticky 单元格 background:inherit，行透明时滑到它下面的
   内容会透上来重影。改磨砂不透明暖白，表头/hover 态同步 */
.process-manage .table-card :deep(.el-table-fixed-column--right) { background-color: rgba(249, 244, 234, 0.97); }
.process-manage .table-card :deep(th.el-table-fixed-column--right) { background-color: rgba(246, 239, 226, 0.98); }
.process-manage .table-card :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) { background-color: rgba(245, 236, 220, 0.98); }

/* 全屏态：面板自身滚动（.table-card 默认 overflow:hidden） */
.process-manage .table-card:fullscreen { overflow: auto; }
</style>
