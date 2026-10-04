<template>
  <div class="customer-snapshot-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="customer-snapshot-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 表格卡片：筛选区 + 操作行 + 表格 + 分页（List Page Spec） -->
    <div ref="panelRef" class="table-card">
    <FilterBar :loading="loading" :pending="listState.hasPendingSearch.value" @search="searchList" @reset="resetFilters">
      <el-input v-model="keyword" placeholder="搜索客户名/ID" clearable class="filter-w-md">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-input v-model="salespersonKeyword" placeholder="业务员姓名/ID" clearable class="filter-w-md">
        <template #prefix><el-icon><User /></el-icon></template>
      </el-input>
      <el-select v-model="isComplete" class="filter-w-sm">
        <el-option label="全部" value="all" />
        <el-option label="已完整" value="true" />
        <el-option label="待补充" value="false" />
      </el-select>


    </FilterBar>

    <div class="action-bar">
      <GlassButton v-permission="'customer:write'" variant="primary" left-icon="Plus" @click="openCreateDialog">手工新增</GlassButton>
      <GlassButton v-permission="'customer:write'" variant="secondary" :loading="autoMatching" @click="handleAutoMatch" left-icon="MagicStick">自动匹配</GlassButton>
      <GlassButton v-permission="'customer:write'" left-icon="Upload" @click="importDialogVisible = true">Excel导入</GlassButton>
      <GlassButton left-icon="Download" @click="downloadTpl">下载模板</GlassButton>
      <TableTools :loading="loading"
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="columnDefs"
        :fullscreen="isFullscreen"
        @refresh="fetchList"
        @fullscreen="toggleFullscreen"
      />
    </div>

    <ListPageStatus v-if="listState.hasData.value && listState.errorMessage.value" :error="listState.errorMessage.value" :loading="loading" :has-data="true" :data-page="listState.dataPage.value" @retry="fetchList" />
<el-table
      :data="tableData"
      v-loading="loading"
      border
      class="list-table"
      :class="densityClass"
      style="width: 100%"
      :row-class-name="rowClassName"
      :max-height="isFullscreen ? undefined : 640"
      @sort-change="changeSort" v-sticky-scrollbar>
      <template #empty><ListPageStatus :error="listState.errorMessage.value" :loading="loading" :has-data="false" @retry="fetchList">
        <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
          <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
        </el-empty>
      </ListPageStatus></template>
      <el-table-column v-if="visibleKeys.includes('customer-id')" prop="customer_id" label="客户ID" min-width="160" max-width="240" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('customer-name')" prop="customer_name" label="客户名称" min-width="160" max-width="240" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('salesperson-name')" prop="salesperson_name" label="业务员" min-width="100" max-width="150" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('salesperson-attribute')" label="业务员属性" min-width="100" max-width="150">
        <template #default="{ row }">
          <span>{{ attrLabel(row.salesperson_attribute) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('salesperson-rate')" label="业务员比例" min-width="100" max-width="150">
        <template #default="{ row }">{{ rateStr(row.salesperson_rate) }}</template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('supervisor-name')" prop="supervisor_name" label="一级主管" min-width="100" max-width="150" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('supervisor-attribute')" label="一级主管属性" min-width="110" max-width="170">
        <template #default="{ row }">
          <span>{{ attrLabel(row.supervisor_attribute) }}</span>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('supervisor-rate')" label="一级主管比例" min-width="110" max-width="170">
        <template #default="{ row }">{{ rateStr(row.supervisor_rate) }}</template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('second-supervisor-name')" prop="second_supervisor_name" label="二级主管" min-width="100" max-width="150" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('second-supervisor-rate')" label="二级主管比例" min-width="110" max-width="170">
        <template #default="{ row }">{{ rateStr(row.second_supervisor_rate) }}</template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('remark')" prop="remark" label="备注" min-width="120" max-width="240" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('first-receipt-date')" prop="first_receipt_date" label="首次成交日期" min-width="120" max-width="180" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="110" max-width="140">
        <template #default="{ row }">
          <StatusBadge v-if="row.is_complete" type="success" size="small" effect="plain">已完整</StatusBadge>
          <StatusBadge v-else type="warning" size="small" effect="plain">待补充</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('source')" label="来源" min-width="70" max-width="110">
        <template #default="{ row }">{{ sourceLabel(row.source) }}</template>
      </el-table-column>
      <el-table-column class-name="table-action-column" label="操作" min-width="180" max-width="270" fixed="right">
        <template #default="{ row }">
          <GlassButton v-if="!row.is_complete" v-permission="'customer:write'" variant="link" left-icon="EditPen" @click="openCompleteDialog(row)">补充信息</GlassButton>
          <GlassButton v-permission="'customer:write'" variant="link" left-icon="RefreshRight" @click="openResetDialog(row)">重置归属</GlassButton>
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
      @current-change="listState.handlePageChange"
      @size-change="handleSizeChange"
    />
    </div>

    <!-- 手工新增 Dialog -->
    <el-dialog v-model="createDialogVisible" title="手工新增客户归属" width="640px">
      <el-form label-position="top" :model="createForm">
        <el-form-item label="客户ID" required>
          <el-input v-model="createForm.customer_id" />
        </el-form-item>
        <el-form-item label="业务员ID" required>
          <el-input v-model="createForm.salesperson_id" />
        </el-form-item>
        <el-form-item label="业务员属性" required>
          <el-select v-model="createForm.salesperson_attribute" style="width:100%">
            <el-option label="开发" value="develop" />
            <el-option label="分配" value="distribute" />
          </el-select>
        </el-form-item>
        <el-form-item label="一级主管ID">
          <el-input v-model="createForm.supervisor_id" />
        </el-form-item>
        <el-form-item label="一级主管属性">
          <el-select v-model="createForm.supervisor_attribute" clearable style="width:100%">
            <el-option label="开发" value="develop" />
            <el-option label="分配" value="distribute" />
          </el-select>
        </el-form-item>
        <el-form-item label="二级主管ID">
          <el-input v-model="createForm.second_supervisor_id" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="createForm.remark" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="createDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitCreate">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- 补充信息 Dialog -->
    <el-dialog v-model="completeDialogVisible" title="补充归属信息" width="640px">
      <el-form label-position="top" :model="completeForm">
        <el-form-item label="业务员">
          <span>{{ currentRow?.salesperson_name || currentRow?.salesperson_id }}</span>
        </el-form-item>
        <el-form-item label="一级主管">
          <span>{{ currentRow?.supervisor_name || currentRow?.supervisor_id || '无' }}</span>
        </el-form-item>
        <el-form-item label="二级主管">
          <span>{{ currentRow?.second_supervisor_name || currentRow?.second_supervisor_id || '无' }}</span>
        </el-form-item>
        <el-form-item label="业务员属性" required>
          <el-select v-model="completeForm.salesperson_attribute" style="width:100%">
            <el-option label="开发" value="develop" />
            <el-option label="分配" value="distribute" />
          </el-select>
        </el-form-item>
        <el-form-item label="一级主管属性">
          <el-select v-model="completeForm.supervisor_attribute" clearable style="width:100%">
            <el-option label="开发" value="develop" />
            <el-option label="分配" value="distribute" />
          </el-select>
        </el-form-item>
        <el-form-item label="业务员比例">
          <el-input-number v-model="completeForm.salesperson_rate" :min="0" :max="100" :precision="1" :step="0.5" :controls="false" style="width:120px" />
          <span style="margin-left:4px">%</span>
        </el-form-item>
        <el-form-item label="一级主管比例">
          <el-input-number v-model="completeForm.supervisor_rate" :min="0" :max="100" :precision="1" :step="0.5" :controls="false" style="width:120px" />
          <span style="margin-left:4px">%</span>
        </el-form-item>
        <el-form-item label="二级主管比例">
          <el-input-number v-model="completeForm.second_supervisor_rate" :min="0" :max="100" :precision="1" :step="0.5" :controls="false" style="width:120px" />
          <span style="margin-left:4px">%</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="completeDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitComplete">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- 重置归属 Dialog -->
    <el-dialog v-model="resetDialogVisible" title="重置客户归属" width="640px">
      <el-form label-position="top" :model="resetForm">
        <el-form-item label="客户">
          <span>{{ currentRow?.customer_name || currentRow?.customer_id }}</span>
        </el-form-item>
        <el-form-item label="业务员ID" required>
          <el-input v-model="resetForm.salesperson_id" />
        </el-form-item>
        <el-form-item label="业务员属性" required>
          <el-select v-model="resetForm.salesperson_attribute" style="width:100%">
            <el-option label="开发" value="develop" />
            <el-option label="分配" value="distribute" />
          </el-select>
        </el-form-item>
        <el-form-item label="一级主管ID">
          <el-input v-model="resetForm.supervisor_id" />
        </el-form-item>
        <el-form-item label="一级主管属性">
          <el-select v-model="resetForm.supervisor_attribute" clearable style="width:100%">
            <el-option label="开发" value="develop" />
            <el-option label="分配" value="distribute" />
          </el-select>
        </el-form-item>
        <el-form-item label="二级主管ID">
          <el-input v-model="resetForm.second_supervisor_id" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="resetForm.remark" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="重置原因" required>
          <el-input v-model="resetForm.reset_reason" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="resetDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitReset">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- 导入 Dialog -->
    <el-dialog v-model="importDialogVisible" title="Excel批量导入客户归属" width="480px">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        模板列：客户ID | 业务员ID | 业务员属性(开发/分配) | 一级主管ID | 一级主管属性(开发/分配) | 二级主管ID
      </el-alert>
      <el-upload drag :auto-upload="false" :limit="1" accept=".xlsx,.xls" :on-change="handleFileChange">
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
        <GlassButton variant="primary" :loading="importing" @click="submitImport" :disabled="!importFile">开始导入</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { useListPage } from '@/composables/useListPage'
import { toRef } from 'vue'
import { msgWarning, msgSuccessText } from '@/utils/feedback'
import { computed, ref, onMounted } from 'vue'

import { getSnapshotList, createSnapshot, completeSnapshot, resetSnapshot, importSnapshots, downloadTemplate, autoMatchSnapshots } from '@/api/customer'
import { downloadUrl } from '@/utils/download'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'

const orderSort = useTableSort()
const columnDefs = [
  { key: 'customer-id', label: '客户ID' }, { key: 'customer-name', label: '客户名称' },
  { key: 'salesperson-name', label: '业务员' }, { key: 'salesperson-attribute', label: '业务员属性' },
  { key: 'salesperson-rate', label: '业务员比例' }, { key: 'supervisor-name', label: '一级主管' },
  { key: 'supervisor-attribute', label: '一级主管属性' }, { key: 'supervisor-rate', label: '一级主管比例' },
  { key: 'second-supervisor-name', label: '二级主管' }, { key: 'second-supervisor-rate', label: '二级主管比例' },
  { key: 'remark', label: '备注' }, { key: 'first-receipt-date', label: '首次成交日期' },
  { key: 'status', label: '状态' }, { key: 'source', label: '来源' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('customer-snapshot', columnDefs)

const listState = useListPage(async (params, context) => {
  return (await getSnapshotList(params, { signal: context.signal, suppressToast: true })).data
}, { immediate: false, searchForm: { keyword: '', salesperson_keyword: '', is_complete: 'all' } })
const { page: page, pageSize: pageSize, total: total, list: tableData, loading: loading } = listState
const fetchList = () => listState.refreshUpdate()
const searchList = () => listState.handleSearch()
const resetFilters = () => listState.handleReset()
const handleSizeChange = size => listState.handleSizeChange(size)
function changeSort(event) { orderSort.onSortChange(event); return listState.handleSortChange(orderSort.sortParams.value) }



const keyword = toRef(listState.searchForm, 'keyword')
const salespersonKeyword = toRef(listState.searchForm, 'salesperson_keyword')
const isComplete = toRef(listState.searchForm, 'is_complete')
const saving = ref(false)
const currentRow = ref(null)
const hasActiveFilters = computed(() => Boolean(listState.appliedSearchForm.value.keyword || listState.appliedSearchForm.value.salesperson_keyword || listState.appliedSearchForm.value.is_complete !== 'all'))

function attrLabel(v) { return { develop: '开发', distribute: '分配' }[v] || '-' }
function rateStr(v) {
  return v != null ? (v * 100).toFixed(1) + '%' : '-'
}
function sourceLabel(v) {
  return { auto: '自动', manual: '手工', import: '导入', init: '初始化' }[v] || v
}
function rowClassName({ row }) {
  return row.is_complete ? '' : 'incomplete-row'
}

// 手工新增
const createDialogVisible = ref(false)
const createForm = ref({ customer_id: '', salesperson_id: '', salesperson_attribute: '', supervisor_id: '', supervisor_attribute: '', second_supervisor_id: '', remark: '' })

function openCreateDialog() {
  createForm.value = { customer_id: '', salesperson_id: '', salesperson_attribute: '', supervisor_id: '', supervisor_attribute: '', second_supervisor_id: '', remark: '' }
  createDialogVisible.value = true
}

async function submitCreate() {
  const f = createForm.value
  if (!f.customer_id || !f.salesperson_id || !f.salesperson_attribute) {
    msgWarning('请填写必填项')
    return
  }
  saving.value = true
  try {
    const payload = { ...f }
    if (!payload.supervisor_id) { payload.supervisor_id = null; payload.supervisor_attribute = null }
    if (!payload.second_supervisor_id) { payload.second_supervisor_id = null }
    if (!payload.remark) { payload.remark = null }
    await createSnapshot(payload)
    msgSuccessText('新增成功')
    createDialogVisible.value = false
    listState.refreshCreate()
  } finally {
    saving.value = false
  }
}

// 补充信息
const completeDialogVisible = ref(false)
const completeForm = ref({ salesperson_attribute: '', supervisor_attribute: '', salesperson_rate: 2.0, supervisor_rate: 1.0, second_supervisor_rate: 0.5 })

function openCompleteDialog(row) {
  currentRow.value = row
  completeForm.value = {
    salesperson_attribute: '',
    supervisor_attribute: '',
    salesperson_rate: 2.0,
    supervisor_rate: row.supervisor_id ? 1.0 : 0,
    second_supervisor_rate: row.second_supervisor_id ? 0.5 : 0,
  }
  completeDialogVisible.value = true
}

async function submitComplete() {
  if (!completeForm.value.salesperson_attribute) {
    msgWarning('请选择业务员属性')
    return
  }
  saving.value = true
  try {
    const f = completeForm.value
    await completeSnapshot(currentRow.value.id, {
      salesperson_attribute: f.salesperson_attribute,
      supervisor_attribute: f.supervisor_attribute || null,
      salesperson_rate: f.salesperson_rate / 100,
      supervisor_rate: f.supervisor_rate / 100,
      second_supervisor_rate: f.second_supervisor_rate / 100,
    })
    msgSuccessText('补全成功')
    completeDialogVisible.value = false
    fetchList()
  } finally {
    saving.value = false
  }
}

// 重置归属
const resetDialogVisible = ref(false)
const resetForm = ref({ salesperson_id: '', salesperson_attribute: '', supervisor_id: '', supervisor_attribute: '', second_supervisor_id: '', remark: '', reset_reason: '' })

function openResetDialog(row) {
  currentRow.value = row
  resetForm.value = {
    salesperson_id: row.salesperson_id || '',
    salesperson_attribute: row.salesperson_attribute || '',
    supervisor_id: row.supervisor_id || '',
    supervisor_attribute: row.supervisor_attribute || '',
    second_supervisor_id: row.second_supervisor_id || '',
    remark: row.remark || '',
    reset_reason: ''
  }
  resetDialogVisible.value = true
}

async function submitReset() {
  const f = resetForm.value
  if (!f.salesperson_id || !f.salesperson_attribute || !f.reset_reason) {
    msgWarning('请填写必填项')
    return
  }
  saving.value = true
  try {
    const payload = { ...f }
    if (!payload.supervisor_id) { payload.supervisor_id = null; payload.supervisor_attribute = null }
    if (!payload.second_supervisor_id) { payload.second_supervisor_id = null }
    if (!payload.remark) { payload.remark = null }
    await resetSnapshot(currentRow.value.id, payload)
    msgSuccessText('重置成功')
    resetDialogVisible.value = false
    fetchList()
  } finally {
    saving.value = false
  }
}

// 导入
const importDialogVisible = ref(false)
const importFile = ref(null)
const importResult = ref(null)
const importing = ref(false)

function handleFileChange(file) { importFile.value = file.raw }

async function submitImport() {
  if (!importFile.value) return
  importing.value = true
  importResult.value = null
  try {
    const res = await importSnapshots(importFile.value)
    importResult.value = res.data
    msgSuccessText(`导入完成：成功 ${res.data.success} 条`)
    fetchList()
  } finally {
    importing.value = false
  }
}

// 自动匹配
const autoMatching = ref(false)

async function handleAutoMatch() {
  autoMatching.value = true
  try {
    const res = await autoMatchSnapshots()
    msgSuccessText(`本次成功匹配${res.data.matched}条，当前还剩${res.data.remaining}条未匹配成功。`)
    fetchList()
  } finally {
    autoMatching.value = false
  }
}

function downloadTpl() {
  downloadUrl(downloadTemplate())
}

onMounted(fetchList)
</script>

<style scoped src="./customer-snapshot.css"></style>
