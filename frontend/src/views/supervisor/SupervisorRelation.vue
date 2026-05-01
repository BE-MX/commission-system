<template>
  <div>
    <!-- 搜索栏 -->
    <el-row :gutter="16" class="toolbar">
      <el-col :span="8">
        <el-input v-model="keyword" placeholder="搜索业务员姓名/ID" clearable @keyup.enter="fetchList" @clear="fetchList">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="4">
        <GlassButton left-icon="Search" @click="fetchList">查询</GlassButton>
        <GlassButton left-icon="Upload" @click="importDialogVisible = true">批量导入</GlassButton>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <div class="table-card">
    <el-table ref="tableRef" :data="tableData" v-loading="loading" border class="list-table" style="width: 100%" :max-height="maxHeight">
      <el-table-column prop="salesperson_id" label="业务员ID" min-width="200" max-width="300" show-overflow-tooltip />
      <el-table-column prop="salesperson_name" label="业务员姓名" min-width="140" max-width="210" show-overflow-tooltip />
      <el-table-column prop="supervisor_id" label="一级主管ID" min-width="200" max-width="300" show-overflow-tooltip />
      <el-table-column prop="supervisor_name" label="一级主管姓名" min-width="140" max-width="210" show-overflow-tooltip />
      <el-table-column prop="second_supervisor_id" label="二级主管ID" min-width="200" max-width="300" show-overflow-tooltip />
      <el-table-column prop="second_supervisor_name" label="二级主管姓名" min-width="140" max-width="210" show-overflow-tooltip />
      <el-table-column prop="effective_start" label="生效日期" min-width="120" max-width="180" show-overflow-tooltip />
      <el-table-column label="操作" min-width="160" max-width="240">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="Edit" @click="openSetDialog(row)">变更主管</GlassButton>
          <GlassButton variant="link" left-icon="Clock" @click="openHistory(row)">查看历史</GlassButton>
        </template>
      </el-table-column>
    </el-table>
    </div>

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

    <!-- 变更主管 Dialog -->
    <el-dialog v-model="setDialogVisible" title="变更主管" width="420px">
      <el-form label-width="100px">
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
    <el-drawer v-model="historyVisible" :title="`${currentRow?.salesperson_name || ''} 主管变更历史`" size="500px">
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
            <el-tag v-if="item.is_current" type="primary" size="small" style="margin-left:8px">当前</el-tag>
          </el-card>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-else description="暂无历史记录" />
    </el-drawer>

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
import { getSupervisorList, setSupervisorRelation, getSupervisorHistory, importSupervisorRelations } from '@/api/supervisor'
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
    const res = await getSupervisorList({ keyword: keyword.value, page: page.value, page_size: pageSize.value })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

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
    ElMessage.warning('请输入一级主管ID')
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
    const res = await getSupervisorHistory({ salesperson_id: row.salesperson_id })
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
    const res = await importSupervisorRelations(importFile.value)
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
