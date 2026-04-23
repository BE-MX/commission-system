<template>
  <div>
    <!-- 顶部工具栏 -->
    <el-row :gutter="16" class="toolbar">
      <el-col :span="6">
        <el-input v-model="keyword" placeholder="搜索客户名/ID" clearable @keyup.enter="fetchList" @clear="fetchList">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="4">
        <el-select v-model="isComplete" @change="fetchList" style="width:100%">
          <el-option label="全部" value="all" />
          <el-option label="已完整" value="true" />
          <el-option label="待补充" value="false" />
        </el-select>
      </el-col>
      <el-col :span="14" style="text-align:right">
        <el-button type="success" :loading="autoMatching" @click="handleAutoMatch"><el-icon><MagicStick /></el-icon> 自动匹配</el-button>
        <el-button type="primary" @click="openCreateDialog"><el-icon><Plus /></el-icon> 手工新增</el-button>
        <el-button @click="importDialogVisible = true"><el-icon><Upload /></el-icon> Excel导入</el-button>
        <el-button @click="downloadTpl"><el-icon><Download /></el-icon> 下载模板</el-button>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <el-table
      ref="tableRef"
      :data="tableData"
      v-loading="loading"
      stripe border
      style="width: 100%"
      :row-class-name="rowClassName"
      :max-height="maxHeight"
    >
      <el-table-column prop="customer_id" label="客户ID" width="160" />
      <el-table-column prop="customer_name" label="客户名称" min-width="160" show-overflow-tooltip />
      <el-table-column prop="salesperson_name" label="业务员" width="100" />
      <el-table-column label="业务员属性" width="100">
        <template #default="{ row }">
          <span>{{ attrLabel(row.salesperson_attribute) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="业务员比例" width="100" align="right">
        <template #default="{ row }">{{ rateStr(row.salesperson_rate) }}</template>
      </el-table-column>
      <el-table-column prop="supervisor_name" label="一级主管" width="100" />
      <el-table-column label="一级主管属性" width="110">
        <template #default="{ row }">
          <span>{{ attrLabel(row.supervisor_attribute) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="一级主管比例" width="110" align="right">
        <template #default="{ row }">{{ rateStr(row.supervisor_rate) }}</template>
      </el-table-column>
      <el-table-column prop="second_supervisor_name" label="二级主管" width="100" />
      <el-table-column label="二级主管比例" width="110" align="right">
        <template #default="{ row }">{{ rateStr(row.second_supervisor_rate) }}</template>
      </el-table-column>
      <el-table-column prop="remark" label="备注" min-width="120" show-overflow-tooltip />
      <el-table-column prop="first_receipt_date" label="首次成交日期" width="120" />
      <el-table-column label="状态" width="90">
        <template #default="{ row }">
          <el-tag v-if="row.is_complete" type="success" size="small">已完整</el-tag>
          <el-tag v-else type="warning" size="small">待补充</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="来源" width="70">
        <template #default="{ row }">{{ sourceLabel(row.source) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="180" fixed="right">
        <template #default="{ row }">
          <el-button v-if="!row.is_complete" link type="warning" @click="openCompleteDialog(row)"><el-icon><EditPen /></el-icon> 补充信息</el-button>
          <el-button link type="primary" @click="openResetDialog(row)"><el-icon><RefreshRight /></el-icon> 重置归属</el-button>
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

    <!-- 手工新增 Dialog -->
    <el-dialog v-model="createDialogVisible" title="手工新增客户归属" width="500px">
      <el-form :model="createForm" label-width="100px">
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
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitCreate">确定</el-button>
      </template>
    </el-dialog>

    <!-- 补充信息 Dialog -->
    <el-dialog v-model="completeDialogVisible" title="补充归属信息" width="500px">
      <el-form :model="completeForm" label-width="110px">
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
        <el-button @click="completeDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitComplete">确定</el-button>
      </template>
    </el-dialog>

    <!-- 重置归属 Dialog -->
    <el-dialog v-model="resetDialogVisible" title="重置客户归属" width="500px">
      <el-form :model="resetForm" label-width="100px">
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
        <el-button @click="resetDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitReset">确定</el-button>
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
        <el-button type="primary" :loading="importing" @click="submitImport" :disabled="!importFile">开始导入</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { getSnapshotList, createSnapshot, completeSnapshot, resetSnapshot, importSnapshots, downloadTemplate, autoMatchSnapshots } from '@/api/customer'
import { downloadUrl } from '@/utils/download'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

const keyword = ref('')
const isComplete = ref('all')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)
const saving = ref(false)
const currentRow = ref(null)

function attrLabel(v) {
  return { develop: '开发', distribute: '分配' }[v] || '-'
}
function rateStr(v) {
  return v != null ? (v * 100).toFixed(1) + '%' : '-'
}
function sourceLabel(v) {
  return { auto: '自动', manual: '手工', import: '导入', init: '初始化' }[v] || v
}
function rowClassName({ row }) {
  return row.is_complete ? '' : 'incomplete-row'
}

async function fetchList() {
  loading.value = true
  try {
    const res = await getSnapshotList({
      keyword: keyword.value, is_complete: isComplete.value,
      page: page.value, page_size: pageSize.value
    })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
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
    ElMessage.warning('请填写必填项')
    return
  }
  saving.value = true
  try {
    const payload = { ...f }
    if (!payload.supervisor_id) { payload.supervisor_id = null; payload.supervisor_attribute = null }
    if (!payload.second_supervisor_id) { payload.second_supervisor_id = null }
    if (!payload.remark) { payload.remark = null }
    await createSnapshot(payload)
    ElMessage.success('新增成功')
    createDialogVisible.value = false
    fetchList()
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
    ElMessage.warning('请选择业务员属性')
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
    ElMessage.success('补全成功')
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
    ElMessage.warning('请填写必填项')
    return
  }
  saving.value = true
  try {
    const payload = { ...f }
    if (!payload.supervisor_id) { payload.supervisor_id = null; payload.supervisor_attribute = null }
    if (!payload.second_supervisor_id) { payload.second_supervisor_id = null }
    if (!payload.remark) { payload.remark = null }
    await resetSnapshot(currentRow.value.id, payload)
    ElMessage.success('重置成功')
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
    ElMessage.success(`导入完成：成功 ${res.data.success} 条`)
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
    ElMessage.success(`本次成功匹配${res.data.matched}条，当前还剩${res.data.remaining}条未匹配成功。`)
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

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
:deep(.incomplete-row) {
  background-color: #fdf6ec !important;
}
</style>
