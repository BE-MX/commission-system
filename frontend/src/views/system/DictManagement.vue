<!--
  列表页标杆模板（标记语言/样式规范）：新列表页复制本文件的结构
  （table-card / list-table / min-width / GlassButton link / el-tag plain / show-overflow-tooltip）。
  服务端分页的编排逻辑另见标杆用例 views/expo/ExpoLeads.vue
  （useListPage + utils/feedback + DetailDrawer，2026-07-03 治理 F-2）。
-->
<template>
  <div class="dict-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="dict-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <el-row :gutter="16" class="toolbar">
      <el-col :span="8">
        <el-select v-model="currentType" placeholder="选择字典类型" style="width: 100%" @change="onTypeChange">
          <el-option
            v-for="t in typeOptions"
            :key="t.type"
            :label="`${t.type}（${t.active_count}/${t.item_count}）`"
            :value="t.type"
          />
        </el-select>
      </el-col>
      <el-col :span="16">
        <GlassButton v-permission="'dict:write'" variant="primary" left-icon="Plus" @click="openCreateDialog">新增字典项</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card dict-panel">
      <el-table ref="tableRef" :data="tableData" v-loading="loading" border class="list-table" style="width: 100%" :max-height="maxHeight">
        <el-table-column prop="code" label="字典编码" min-width="140" max-width="210" show-overflow-tooltip sortable />
        <el-table-column prop="label" label="显示名" min-width="140" max-width="210" show-overflow-tooltip sortable />
        <el-table-column prop="sort" label="排序" min-width="80" max-width="120" sortable />
        <el-table-column label="状态" min-width="80" max-width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column label="操作" min-width="240" max-width="360" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'dict:write'" variant="link" left-icon="Edit" @click="openEditDialog(row)">编辑</GlassButton>
            <GlassButton v-permission="'dict:write'" variant="link" :link-tone="row.is_active ? '' : 'success'" left-icon="SwitchButton" @click="handleToggleActive(row)">
              {{ row.is_active ? '禁用' : '启用' }}
            </GlassButton>
            <GlassButton v-permission="'dict:write'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑 Dialog -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑字典项' : '新增字典项'" width="480px">
      <el-form ref="formRef" :model="form" :rules="formRules" label-width="80px">
        <el-form-item label="字典类型" prop="type" v-if="!isEdit">
          <el-select v-model="form.type" placeholder="选择字典类型" style="width: 100%">
            <el-option v-for="t in typeOptions" :key="t.type" :label="t.type" :value="t.type" />
          </el-select>
        </el-form-item>
        <el-form-item label="字典编码" prop="code">
          <el-input v-model="form.code" :disabled="isEdit" placeholder="英文或数字，不可修改" />
        </el-form-item>
        <el-form-item label="显示名" prop="label">
          <el-input v-model="form.label" placeholder="中文显示名" />
        </el-form-item>
        <el-form-item label="排序">
          <el-input-number v-model="form.sort" :min="0" :max="9999" style="width: 100%" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="form.remark" type="textarea" :rows="2" placeholder="选填" />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="dialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitForm">确定</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getDictTypes, getDictItems, createDictItem, updateDictItem, deleteDictItem } from '@/api/system'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

const typeOptions = ref([])
const currentType = ref('')
const tableData = ref([])
const loading = ref(false)
const saving = ref(false)
const dialogVisible = ref(false)
const isEdit = ref(false)
const editId = ref(null)
const formRef = ref()
const form = ref({ type: '', code: '', label: '', sort: 0, remark: '' })

const formRules = {
  type: [{ required: true, message: '请选择字典类型', trigger: 'change' }],
  code: [{ required: true, message: '请输入字典编码', trigger: 'blur' }],
  label: [{ required: true, message: '请输入显示名', trigger: 'blur' }],
}

async function fetchTypes() {
  try {
    const res = await getDictTypes()
    typeOptions.value = res.data || []
    if (typeOptions.value.length && !currentType.value) {
      currentType.value = typeOptions.value[0].type
      fetchItems()
    }
  } catch {
    typeOptions.value = []
  }
}

async function fetchItems() {
  if (!currentType.value) return
  loading.value = true
  try {
    const res = await getDictItems(currentType.value, false)
    tableData.value = res.data || []
  } finally {
    loading.value = false
  }
}

function onTypeChange() {
  fetchItems()
}

function openCreateDialog() {
  isEdit.value = false
  editId.value = null
  form.value = { type: currentType.value || '', code: '', label: '', sort: 0, remark: '' }
  dialogVisible.value = true
}

function openEditDialog(row) {
  isEdit.value = true
  editId.value = row.id
  form.value = { type: row.type, code: row.code, label: row.label, sort: row.sort || 0, remark: row.remark || '' }
  dialogVisible.value = true
}

async function submitForm() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  saving.value = true
  try {
    if (isEdit.value) {
      await updateDictItem(editId.value, { label: form.value.label, sort: form.value.sort, remark: form.value.remark })
      ElMessage.success('更新成功')
    } else {
      await createDictItem({ type: form.value.type, code: form.value.code, label: form.value.label, sort: form.value.sort, remark: form.value.remark })
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchItems()
  } catch {
    // handled by interceptor
  } finally {
    saving.value = false
  }
}

async function handleToggleActive(row) {
  const action = row.is_active ? '禁用' : '启用'
  try {
    await ElMessageBox.confirm(`确认${action}字典项「${row.label}」？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await updateDictItem(row.id, { is_active: !row.is_active })
    ElMessage.success(`已${action}`)
    fetchItems()
  } catch { /* handled by interceptor */ }
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(`确认删除字典项「${row.label}」？此操作不可恢复。`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await deleteDictItem(row.id)
    ElMessage.success('删除成功')
    fetchItems()
  } catch { /* handled by interceptor */ }
}

onMounted(fetchTypes)
</script>

<style scoped>
/* 极光层（.lg-aurora，与工作台同源）定位上下文 */
.dict-page {
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.dict-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。必须点名内容块，不能用 > :not(.lg-aurora)——
   el-dialog 默认就地渲染，通配会覆盖 .el-overlay 的 position: fixed */
.dict-page .toolbar,
.dict-page .dict-panel {
  position: relative;
  z-index: 1;
}

.toolbar { margin-bottom: 16px; }

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.dict-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.dict-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：磨砂但不透明的暖白，表头/hover 态同步 */
.dict-panel :deep(.el-table-fixed-column--right) {
  background-color: rgba(249, 244, 234, 0.97);
}
.dict-panel :deep(th.el-table-fixed-column--right) {
  background-color: rgba(246, 239, 226, 0.98);
}
.dict-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) {
  background-color: rgba(245, 236, 220, 0.98);
}
</style>
