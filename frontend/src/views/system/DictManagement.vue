<template>
  <div class="dict-page">
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
        <GlassButton variant="primary" left-icon="Plus" @click="openCreateDialog">新增字典项</GlassButton>
      </el-col>
    </el-row>

    <div class="table-card">
      <el-table ref="tableRef" :data="tableData" v-loading="loading" border class="list-table" style="width: 100%" :max-height="maxHeight">
        <el-table-column prop="code" label="字典编码" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column prop="label" label="显示名" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column prop="sort" label="排序" min-width="80" max-width="120" />
        <el-table-column label="状态" min-width="80" max-width="120">
          <template #default="{ row }">
            <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">{{ row.is_active ? '启用' : '禁用' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="remark" label="备注" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column label="操作" min-width="240" max-width="360" fixed="right">
          <template #default="{ row }">
            <GlassButton variant="link" left-icon="Edit" @click="openEditDialog(row)">编辑</GlassButton>
            <GlassButton variant="link" :link-tone="row.is_active ? '' : 'success'" left-icon="SwitchButton" @click="handleToggleActive(row)">
              {{ row.is_active ? '禁用' : '启用' }}
            </GlassButton>
            <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
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
.toolbar { margin-bottom: 16px; }
</style>
