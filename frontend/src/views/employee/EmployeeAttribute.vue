<template>
  <div class="employee-attr-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="employee-attr-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 表格卡片：筛选区 + 操作行 + 表格 + 分页（List Page Spec） -->
    <div ref="panelRef" class="table-card">
    <div class="toolbar">
      <el-input v-model="keyword" placeholder="搜索姓名/ID" clearable class="filter-w-md" @keyup.enter="searchList" @clear="searchList">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <GlassButton variant="primary" left-icon="Search" @click="searchList">查询</GlassButton>
      <GlassButton left-icon="RefreshLeft" @click="resetFilter">重置</GlassButton>
    </div>

    <div class="action-bar">
      <GlassButton v-permission="'employee:write'" left-icon="Upload" @click="importDialogVisible = true">批量导入</GlassButton>
      <TableTools
        v-model:visible-keys="visibleKeys"
        v-model:density="density"
        :columns="columnDefs"
        :fullscreen="isFullscreen"
        @refresh="fetchList"
        @fullscreen="toggleFullscreen"
      />
    </div>

    <el-table :data="tableData" v-loading="loading" border class="list-table" :class="densityClass" style="width: 100%" :max-height="isFullscreen ? undefined : 640" @sort-change="orderSort.onSortChange">
      <template #empty>
        <el-empty :image-size="96" :description="keyword ? '没有符合条件的记录' : '暂无数据'">
          <GlassButton v-if="keyword" left-icon="RefreshLeft" @click="resetFilter">重置筛选</GlassButton>
        </el-empty>
      </template>
      <el-table-column v-if="visibleKeys.includes('user-id')" prop="user_id" label="员工ID" min-width="200" max-width="300" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('full-name')" prop="full_name" label="姓名" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('nickname')" prop="nickname" label="昵称" min-width="140" max-width="210" show-overflow-tooltip />
      <el-table-column v-if="visibleKeys.includes('current-attribute')" prop="current_attribute" label="当前属性" min-width="120" max-width="180" sortable="custom">
        <template #default="{ row }">
          <span v-if="row.current_attribute === 'develop'" class="badge-dev">开发</span>
          <span v-else-if="row.current_attribute === 'distribute'" class="badge-assign">分配</span>
          <el-tag v-else type="info" size="small" effect="plain">未设置</el-tag>
        </template>
      </el-table-column>
      <el-table-column class-name="table-action-column" label="操作" min-width="160" max-width="240">
        <template #default="{ row }">
          <GlassButton v-permission="'employee:write'" variant="link" left-icon="Edit" @click="openSetDialog(row)">设置属性</GlassButton>
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
      @current-change="fetchList"
      @size-change="handleSizeChange"
    />
    </div>

    <!-- 设置属性 Dialog -->
    <el-dialog v-model="setDialogVisible" title="设置员工属性" width="420px">
      <el-form label-width="80px">
        <el-form-item label="员工">
          <span>{{ currentRow?.full_name || currentRow?.user_id }}</span>
        </el-form-item>
        <el-form-item label="属性">
          <el-select v-model="attrForm.attribute_type" placeholder="请选择" style="width: 100%">
            <el-option label="开发" value="develop" />
            <el-option label="分配" value="distribute" />
          </el-select>
        </el-form-item>
        <el-form-item label="生效时间">
          <el-date-picker
            v-model="attrForm.effective_date"
            type="date"
            placeholder="选择生效日期"
            value-format="YYYY-MM-DD"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="setDialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitAttribute">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- 历史 Drawer -->
    <el-drawer v-model="historyVisible" :title="`${currentRow?.full_name || ''} 属性变更历史`" size="400px">
      <el-timeline v-if="historyList.length">
        <el-timeline-item
          v-for="item in historyList"
          :key="item.id"
          :timestamp="item.effective_start"
          placement="top"
        >
          <el-card shadow="never" body-style="padding: 12px">
            <el-tag :type="item.attribute_type === 'develop' ? 'success' : 'warning'" size="small">
              {{ item.attribute_type === 'develop' ? '开发' : '分配' }}
            </el-tag>
            <span v-if="item.effective_end" class="history-range"> ~ {{ item.effective_end }}</span>
            <el-tag v-if="item.is_current" type="primary" size="small" style="margin-left:8px">当前</el-tag>
          </el-card>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无历史记录" />
    </el-drawer>

    <!-- 批量导入 Dialog -->
    <el-dialog v-model="importDialogVisible" title="批量导入员工属性" width="480px">
      <el-alert type="info" :closable="false" style="margin-bottom:16px">
        Excel 模板列：员工ID(user_id) | 属性(开发/分配)
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
        <el-descriptions :column="3" border size="small">
          <el-descriptions-item label="总行数">{{ importResult.total_rows }}</el-descriptions-item>
          <el-descriptions-item label="成功">{{ importResult.success }}</el-descriptions-item>
          <el-descriptions-item label="失败">{{ importResult.failed }}</el-descriptions-item>
        </el-descriptions>
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
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getEmployeeList, setEmployeeAttribute, getAttributeHistory, importEmployeeAttributes } from '@/api/employee'
import { useTableSort } from '@/composables/useTableSort'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'
import { currentBeijingDate } from '@/utils/datetime'

const orderSort = useTableSort()

// 列显隐元数据（TableTools 列设置面板数据源，Action Bar Spec）
const columnDefs = [
  { key: 'user-id', label: '员工ID' },
  { key: 'full-name', label: '姓名' },
  { key: 'nickname', label: '昵称' },
  { key: 'current-attribute', label: '当前属性' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } =
  useTableView('employee-attribute', columnDefs)

const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

async function fetchList() {
  loading.value = true
  try {
    const res = await getEmployeeList({ keyword: keyword.value, page: page.value, page_size: pageSize.value, ...orderSort.sortParams.value })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

// 查询/重置成对（List Page Spec 第 5 节）：回第 1 页再加载
function searchList() {
  page.value = 1
  fetchList()
}

function resetFilter() {
  keyword.value = ''
  page.value = 1
  fetchList()
}

function handleSizeChange() {
  page.value = 1
  fetchList()
}

// 设置属性
const setDialogVisible = ref(false)
const currentRow = ref(null)
const attrForm = ref({ attribute_type: '', effective_date: '' })
const saving = ref(false)

function formatToday() {
  return currentBeijingDate()
}

function openSetDialog(row) {
  currentRow.value = row
  attrForm.value.attribute_type = row.current_attribute || ''
  attrForm.value.effective_date = formatToday()
  setDialogVisible.value = true
}

async function submitAttribute() {
  if (!attrForm.value.attribute_type) {
    ElMessage.warning('请选择属性')
    return
  }
  saving.value = true
  try {
    await setEmployeeAttribute({
      employee_id: currentRow.value.user_id,
      attribute_type: attrForm.value.attribute_type,
      effective_date: attrForm.value.effective_date || undefined
    })
    ElMessage.success('设置成功')
    setDialogVisible.value = false
    fetchList()
  } finally {
    saving.value = false
  }
}

// 查看历史
const historyVisible = ref(false)
const historyList = ref([])

async function openHistory(row) {
  currentRow.value = row
  historyVisible.value = true
  try {
    const res = await getAttributeHistory({ employee_id: row.user_id })
    historyList.value = res.data || []
  } catch {
    historyList.value = []
  }
}

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
    const res = await importEmployeeAttributes(importFile.value)
    importResult.value = res.data
    ElMessage.success(`导入完成：成功 ${res.data.success} 条`)
    fetchList()
  } finally {
    importing.value = false
  }
}

onMounted(fetchList)
</script>

<style scoped>
.employee-attr-page { position: relative; }

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.employee-attr-aurora { inset: -24px -28px; }

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   el-drawer/el-dialog 默认就地渲染（append-to-body=false），通配会覆盖
   .el-overlay 的 position: fixed，抽屉/弹窗打开后看不见 */
.employee-attr-page .table-card {
  position: relative;
  z-index: 1;
}

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 白底） */
.employee-attr-page .table-card {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.employee-attr-page .table-card :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

.history-range { color: var(--text-muted); font-size: 12px; margin-left: 4px; }
</style>
