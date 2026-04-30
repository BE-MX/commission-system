<template>
  <div>
    <!-- 搜索栏 -->
    <el-row :gutter="16" class="toolbar">
      <el-col :span="8">
        <el-input v-model="keyword" placeholder="搜索姓名/ID" clearable @keyup.enter="fetchList" @clear="fetchList">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="4">
        <el-button type="primary" @click="fetchList"><el-icon><Search /></el-icon> 查询</el-button>
        <el-button @click="importDialogVisible = true"><el-icon><Upload /></el-icon> 批量导入</el-button>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <el-table ref="tableRef" :data="tableData" v-loading="loading" stripe border style="width: 100%" :max-height="maxHeight">
      <el-table-column prop="user_id" label="员工ID" width="200" />
      <el-table-column prop="full_name" label="姓名" width="140" />
      <el-table-column prop="nickname" label="昵称" width="140" />
      <el-table-column label="当前属性" width="120">
        <template #default="{ row }">
          <el-tag v-if="row.current_attribute === 'develop'" type="success">开发</el-tag>
          <el-tag v-else-if="row.current_attribute === 'distribute'" type="warning">分配</el-tag>
          <el-tag v-else type="info">未设置</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" min-width="160">
        <template #default="{ row }">
          <el-button link type="primary" @click="openSetDialog(row)"><el-icon><Edit /></el-icon> 设置属性</el-button>
          <el-button link type="primary" @click="openHistory(row)"><el-icon><Clock /></el-icon> 查看历史</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      class="pagination"
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      layout="total, prev, pager, next, sizes"
      :page-sizes="[20, 50, 100]"
      @current-change="fetchList"
      @size-change="fetchList"
    />

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
        <el-button @click="setDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitAttribute">确定</el-button>
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
        <el-button @click="importDialogVisible = false">关闭</el-button>
        <el-button type="primary" :loading="importing" @click="submitImport" :disabled="!importFile">
          开始导入
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getEmployeeList, setEmployeeAttribute, getAttributeHistory, importEmployeeAttributes } from '@/api/employee'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)

async function fetchList() {
  loading.value = true
  try {
    const res = await getEmployeeList({ keyword: keyword.value, page: page.value, page_size: pageSize.value })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

// 设置属性
const setDialogVisible = ref(false)
const currentRow = ref(null)
const attrForm = ref({ attribute_type: '', effective_date: '' })
const saving = ref(false)

function formatToday() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
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
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
.history-range { color: var(--text-muted); font-size: 12px; margin-left: 4px; }
</style>
