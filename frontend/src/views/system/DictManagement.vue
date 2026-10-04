<!--
  列表页结构示例（标记语言/样式规范）：table-card（内含 .toolbar 筛选区 / .action-bar 操作行 + TableTools /
  list-table）+ min-width + max-width / GlassButton link / el-tag plain / show-overflow-tooltip，
  完整规范见 DESIGN.md「List Page Spec / Action Bar Spec」。
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

    <div ref="panelRef" class="table-card dict-panel">
      <ListPageStatus :error="typesResource.errorMessage.value" :loading="typesResource.loading.value" :has-data="typesResource.hasData.value" @retry="fetchTypes" />
      <div class="toolbar">
        <el-select v-model="currentType" placeholder="选择字典类型" class="filter-w-lg" @change="onTypeChange">
          <el-option
            v-for="t in typeOptions"
            :key="t.type"
            :label="`${t.type}（${t.active_count}/${t.item_count}）`"
            :value="t.type"
          />
        </el-select>
        <GlassButton variant="primary" left-icon="Search" @click="fetchItems">查询</GlassButton>
        <GlassButton left-icon="RefreshLeft" @click="resetFilters">重置</GlassButton>
      </div>

      <div class="action-bar">
        <GlassButton v-permission="'dict:write'" variant="primary" left-icon="Plus" @click="openCreateDialog">新增字典项</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading" @refresh="fetchItems"
          @fullscreen="toggleFullscreen"
        />
      </div>

      <ListPageStatus v-if="itemsResource.hasData.value" :error="itemsResource.errorMessage.value" :loading="itemsResource.loading.value" :has-data="itemsResource.hasData.value" @retry="reloadRows" />
      <el-table :data="tableData" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" v-sticky-scrollbar>
        <template #empty><ListPageStatus :error="itemsResource.errorMessage.value" :loading="loading" @retry="reloadRows">
          <el-empty :image-size="96" description="暂无数据" />
        </ListPageStatus></template>
        <el-table-column v-if="visibleKeys.includes('code')" prop="code" label="字典编码" min-width="140" max-width="210" show-overflow-tooltip sortable />
        <el-table-column v-if="visibleKeys.includes('label')" prop="label" label="显示名" min-width="140" max-width="210" show-overflow-tooltip sortable />
        <el-table-column v-if="visibleKeys.includes('sort')" prop="sort" label="排序" min-width="80" max-width="120" sortable />
        <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="100" max-width="120">
          <template #default="{ row }">
            <StatusBadge :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">{{ row.is_active ? '启用' : '禁用' }}</StatusBadge>
          </template>
        </el-table-column>
        <el-table-column v-if="visibleKeys.includes('remark')" prop="remark" label="备注" min-width="140" max-width="210" show-overflow-tooltip />
        <el-table-column class-name="table-action-column" label="操作" min-width="240" max-width="360" fixed="right">
          <template #default="{ row }">
            <GlassButton v-permission="'dict:write'" variant="link" left-icon="Edit" @click="openEditDialog(row)">编辑</GlassButton>
            <GlassButton v-permission="'dict:write'" variant="link" :link-tone="row.is_active ? 'warning' : 'success'" left-icon="SwitchButton" @click="handleToggleActive(row)">
              {{ row.is_active ? '禁用' : '启用' }}
            </GlassButton>
            <GlassButton v-permission="'dict:write'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 新增/编辑 Dialog -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑字典项' : '新增字典项'" width="480px">
      <el-form label-position="top" ref="formRef" :model="form" :rules="formRules">
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
import { useAsyncResource } from '@/composables/useAsyncResource'
import { msgSuccessText, confirmAction } from '@/utils/feedback'
import { ref, onMounted } from 'vue'

import { getDictTypes, getDictItems, createDictItem, updateDictItem, deleteDictItem } from '@/api/system'
import { useTableView } from '@/composables/useTableView'
import TableTools from '@/components/TableTools.vue'

// 列显隐元数据（TableTools 面板数据源，不驱动列渲染）
const columnDefs = [
  { key: 'code', label: '字典编码' },
  { key: 'label', label: '显示名' },
  { key: 'sort', label: '排序' },
  { key: 'status', label: '状态' },
  { key: 'remark', label: '备注' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('dict-management', columnDefs)

const typesResource = useAsyncResource(async (_, { signal }) => (await getDictTypes({ signal, suppressToast: true })).data || [], { initialData: [] })
const typeOptions = typesResource.data
const currentType = ref('')
const itemsResource = useAsyncResource(async ({ type }, { signal }) => {
  if (!type) return []
  return (await getDictItems(type, false, { signal, suppressToast: true })).data || []
}, { initialData: [] })
const tableData = itemsResource.data
const loading = itemsResource.loading
let loadedType = ''
const reloadRows = () => fetchItems()
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
  const success = await typesResource.load()
  if (success && typeOptions.value.length && !currentType.value) {
    currentType.value = typeOptions.value[0].type
    await fetchItems()
  }
}

function fetchItems() {
  const type = currentType.value
  const clear = loadedType !== type
  loadedType = type
  return itemsResource.load({ type }, { clear })
}

function onTypeChange() {
  fetchItems()
}

// 类型选择器是必选分类而非可清空筛选：重置=回到首个类型（页面初始默认态）并重载
function resetFilters() {
  currentType.value = typeOptions.value[0]?.type || ''
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
      msgSuccessText('更新成功')
    } else {
      await createDictItem({ type: form.value.type, code: form.value.code, label: form.value.label, sort: form.value.sort, remark: form.value.remark })
      msgSuccessText('创建成功')
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
    await confirmAction(`确认${action}字典项「${row.label}」？`, '确认', { type: 'warning' })
  } catch { return }
  try {
    await updateDictItem(row.id, { is_active: !row.is_active })
    msgSuccessText(`已${action}`)
    fetchItems()
  } catch { /* handled by interceptor */ }
}

async function handleDelete(row) {
  try {
    await confirmAction(`确认删除字典项「${row.label}」？此操作不可恢复。`, '删除确认', { type: 'warning' })
  } catch { return }
  try {
    await deleteDictItem(row.id)
    msgSuccessText('删除成功')
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
.dict-page .dict-panel {
  position: relative;
  z-index: 1;
}

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
