<template>
  <div class="process-manage">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="process-manage-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 工具栏 -->
    <div class="toolbar">
      <div class="toolbar-left">
        <el-input v-model="searchName" placeholder="搜索工序名称" clearable style="width: 220px" @clear="loadData" @keyup.enter="loadData">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 120px" @change="loadData">
          <el-option label="启用" :value="1" />
          <el-option label="禁用" :value="0" />
        </el-select>
        <GlassButton variant="primary" @click="loadData">搜索</GlassButton>
      </div>
      <GlassButton variant="primary" :left-icon="Plus" @click="openForm()">新增工序</GlassButton>
    </div>

    <!-- 表格 -->
    <div class="table-card">
      <el-table :data="items" v-loading="loading" border class="list-table">
        <el-table-column prop="id" label="ID" min-width="70" max-width="100" show-overflow-tooltip />
        <el-table-column prop="name" label="工序名称" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column prop="description" label="描述" min-width="200" max-width="300" show-overflow-tooltip />
        <el-table-column prop="sort_order" label="排序" min-width="80" max-width="120" />
        <el-table-column label="客户进度页" min-width="110" max-width="140">
          <template #default="{ row }">
            <el-tag :type="row.show_in_domestic_track ? 'success' : 'info'" size="small" effect="plain">
              {{ row.show_in_domestic_track ? '显示' : '隐藏' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" min-width="80" max-width="120">
          <template #default="{ row }">
            <el-tag :type="row.status === 1 ? 'success' : 'info'" size="small" effect="plain">
              {{ row.status === 1 ? '启用' : '禁用' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" min-width="160" max-width="240">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="240" max-width="360" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="Edit" @click="openForm(row)">编辑</GlassButton>
            <GlassButton variant="link" :link-tone="row.status === 1 ? 'warning' : 'success'" left-icon="SwitchButton" @click="toggleStatus(row)">
              {{ row.status === 1 ? '禁用' : '启用' }}
            </GlassButton>
            <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 分页 -->
    <div class="pagination-wrap">
      <el-pagination background layout="total, prev, pager, next" :total="total" :page-size="pageSize" v-model:current-page="page" @current-change="loadData" />
    </div>

    <!-- 新增/编辑弹窗 -->
    <el-dialog v-model="formVisible" :title="form.id ? '编辑工序' : '新增工序'" width="480" destroy-on-close>
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="80px">
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
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Search } from '@element-plus/icons-vue'
import * as api from '@/api/production'

const loading = ref(false)
const items = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const searchName = ref('')
const filterStatus = ref(null)

const formVisible = ref(false)
const submitting = ref(false)
const form = ref({ name: '', description: '', sort_order: 0, show_in_domestic_track: 1 })
const formRef = ref(null)
const formRules = {
  name: [{ required: true, message: '请输入工序名称', trigger: 'blur' }, { min: 2, max: 100, message: '2-100字', trigger: 'blur' }],
}

function formatTime(dt) {
  if (!dt) return ''
  return new Date(dt).toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

async function loadData() {
  loading.value = true
  try {
    const res = await api.getProcesses({ page: page.value, page_size: pageSize.value, name: searchName.value || undefined, status: filterStatus.value ?? undefined })
    items.value = res.items || []
    total.value = res.total || 0
  } finally {
    loading.value = false
  }
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
    ElMessage.success(form.value.id ? '已更新' : '已创建')
    formVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  } finally {
    submitting.value = false
  }
}

async function toggleStatus(row) {
  const newStatus = row.status === 1 ? 0 : 1
  const label = newStatus === 0 ? '禁用' : '启用'
  try {
    await api.updateProcess(row.id, { status: newStatus })
    ElMessage.success(`已${label}`)
    loadData()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm('删除后不可恢复，确认删除？', '提示', { type: 'warning' })
    await api.deleteProcess(row.id)
    ElMessage.success('已删除')
    loadData()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '删除失败')
  }
}

onMounted(loadData)
</script>

<style scoped>
.process-manage { padding: 20px; position: relative; }

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.process-manage-aurora { inset: -24px -28px; }

/* 内容压到极光之上。点名内容块，不能用 > :not(.lg-aurora) 通配——
   el-dialog 默认就地渲染（append-to-body=false），通配会覆盖
   .el-overlay 的 position: fixed，弹窗打开后看不见 */
.process-manage .toolbar,
.process-manage .table-card,
.process-manage .pagination-wrap {
  position: relative;
  z-index: 1;
}

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 白底） */
.process-manage .table-card {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

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
.toolbar { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.toolbar-left { display: flex; gap: 10px; align-items: center; }
.pagination-wrap { display: flex; justify-content: flex-end; margin-top: 16px; }
</style>
