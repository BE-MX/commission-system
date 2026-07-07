<template>
  <div>
    <!-- 操作栏 -->
    <el-row :gutter="16" class="toolbar">
      <el-col :span="24">
        <GlassButton variant="primary" left-icon="Plus" @click="openCreateDialog">新增角色</GlassButton>
      </el-col>
    </el-row>

    <!-- 角色列表 -->
    <div class="table-card">
    <el-table ref="tableRef" :data="tableData" v-loading="loading" border class="list-table" style="width: 100%" :max-height="maxHeight">
      <el-table-column prop="name" label="角色标识" min-width="140" max-width="210" show-overflow-tooltip sortable />
      <el-table-column prop="label" label="角色名称" min-width="140" max-width="210" show-overflow-tooltip sortable />
      <el-table-column prop="description" label="描述" min-width="200" max-width="300" show-overflow-tooltip />
      <el-table-column label="类型" min-width="100" max-width="150">
        <template #default="{ row }">
          <el-tag :type="row.is_system ? 'warning' : 'primary'" size="small" effect="plain">{{ row.is_system ? '系统' : '自定义' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="user_count" label="用户数" min-width="80" max-width="120" show-overflow-tooltip sortable />
      <el-table-column prop="permission_count" label="权限数" min-width="80" max-width="120" show-overflow-tooltip sortable />
      <el-table-column prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip sortable />
      <el-table-column label="操作" min-width="220" max-width="300" fixed="right">
        <template #default="{ row }">
          <GlassButton variant="link" :disabled="row.name === 'super_admin'" @click="openEditDialog(row)" left-icon="Edit">
            编辑
          </GlassButton>
          <GlassButton variant="link" :disabled="row.name === 'super_admin'" @click="openPermDrawer(row)" left-icon="Lock">
            权限
          </GlassButton>
          <GlassButton variant="link" link-tone="danger" :disabled="row.name === 'super_admin' || row.user_count > 0" @click="handleDelete(row)" left-icon="Delete">
            删除
          </GlassButton>
        </template>
      </el-table-column>
    </el-table>
    </div>

    <!-- 新增/编辑基本信息 Dialog -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑角色' : '新增角色'" width="560px">
      <el-form :model="form" label-width="80px">
        <el-form-item label="角色标识" required>
          <el-input v-model="form.name" placeholder="英文标识，如 manager" :disabled="isEdit" />
        </el-form-item>
        <el-form-item label="角色名称" required>
          <el-input v-model="form.label" placeholder="中文名称" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" placeholder="选填" :rows="2" />
        </el-form-item>
        <el-form-item v-if="!isEdit" label="权限">
          <span class="form-tip">创建后在列表点击「权限」进入矩阵配置</span>
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="dialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitForm">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- 权限矩阵 Drawer（90% 宽） -->
    <el-drawer v-model="drawerVisible" size="90%" :with-header="false" class="perm-drawer">
      <div class="drawer-shell">
        <div class="drawer-head">
          <span class="title">编辑角色权限</span>
          <span class="role-tag">{{ drawerRole?.name }} · {{ drawerRole?.label }}</span>
          <div class="tabs">
            <span class="tab" :class="{ on: activeTab === 'matrix' }" @click="activeTab = 'matrix'">权限矩阵</span>
            <span class="tab" :class="{ on: activeTab === 'nav' }" @click="activeTab = 'nav'">按导航查看</span>
          </div>
          <span class="sel-count">已选 {{ matrix.selectedCount }} 项</span>
          <div class="spacer" />
          <el-select
            v-model="matrix.templateKey" placeholder="套用模板" clearable
            style="width: 170px" @change="onTemplateChange"
          >
            <el-option v-for="t in ROLE_TEMPLATES" :key="t.key" :label="t.all ? `${t.label}（全部权限）` : t.label" :value="t.key" />
          </el-select>
          <el-input v-model="matrix.searchText" placeholder="搜索模块 / 权限…" clearable style="width: 200px">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
        </div>

        <div class="drawer-body" v-loading="matrix.loading">
          <PermissionMatrixTab v-show="activeTab === 'matrix'" :matrix="matrix" />
          <PermissionNavTab
            v-if="activeTab === 'nav'"
            :selected-codes="matrix.selectedCodesList"
            :label-map="matrix.codeLabelMap"
            @locate="onLocate"
          />
        </div>

        <div class="diffbar">
          <span>本次变更：<span class="add">+{{ matrix.addedCodes.length }}</span> / <span class="del">−{{ matrix.removedCodes.length }}</span></span>
          <span v-if="matrix.legacySelectedCount" class="lg">含 {{ matrix.legacySelectedCount }} 个已下架旧权限将在保存时自动移除</span>
          <div class="spacer" />
          <GlassButton v-if="matrix.templateKey" variant="ghost" @click="resetToTemplate">重置为模板</GlassButton>
          <GlassButton variant="ghost" @click="drawerVisible = false">取消</GlassButton>
          <GlassButton variant="primary" :loading="savingPerms" :disabled="!matrix.hasChanges" @click="savePermissions">
            保存（确认变更明细）
          </GlassButton>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessageBox } from 'element-plus'
import { getRoleList, createRole, updateRole, deleteRole } from '@/api/userManagement'
import { msgSuccess, msgError, confirmDanger } from '@/utils/feedback'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { ROLE_TEMPLATES } from '@/config/roleTemplates'
import { usePermissionMatrix } from './composables/usePermissionMatrix'
import PermissionMatrixTab from './components/PermissionMatrixTab.vue'
import PermissionNavTab from './components/PermissionNavTab.vue'

const { tableRef, maxHeight } = useTableMaxHeight()

const tableData = ref([])
const loading = ref(false)
const saving = ref(false)

// ── 列表查询 ────────────────────────────────────────
async function fetchList() {
  loading.value = true
  try {
    const res = await getRoleList()
    tableData.value = res.data || []
  } finally {
    loading.value = false
  }
}

// ── 新增 / 编辑基本信息 ─────────────────────────────
const dialogVisible = ref(false)
const isEdit = ref(false)
const editRoleId = ref(null)
const form = ref({ name: '', label: '', description: '', permission_ids: [] })

function openCreateDialog() {
  isEdit.value = false
  editRoleId.value = null
  form.value = { name: '', label: '', description: '', permission_ids: [] }
  dialogVisible.value = true
}

function openEditDialog(row) {
  isEdit.value = true
  editRoleId.value = row.id
  form.value = {
    name: row.name,
    label: row.label,
    description: row.description || '',
    // 基本信息编辑不动权限，原样回传保持不变
    permission_ids: (row.permission_ids || []).map(Number),
  }
  dialogVisible.value = true
}

async function submitForm() {
  if (!form.value.label) {
    msgError('请填写角色名称')
    return
  }
  if (!isEdit.value && !form.value.name) {
    msgError('请填写角色标识')
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await updateRole(editRoleId.value, {
        label: form.value.label,
        description: form.value.description || null,
        permission_ids: form.value.permission_ids,
      })
      msgSuccess('更新')
    } else {
      await createRole(form.value)
      msgSuccess('创建')
    }
    dialogVisible.value = false
    fetchList()
  } catch {
    // handled by interceptor
  } finally {
    saving.value = false
  }
}

// ── 权限矩阵抽屉 ────────────────────────────────────
const matrix = usePermissionMatrix()
const drawerVisible = ref(false)
const drawerRole = ref(null)
const activeTab = ref('matrix')
const savingPerms = ref(false)

async function openPermDrawer(row) {
  drawerRole.value = row
  activeTab.value = 'matrix'
  drawerVisible.value = true
  if (!matrix.allPerms.length) await matrix.loadPermissions()
  matrix.initSelection(row.permission_ids || [])
}

function onTemplateChange(key) {
  if (!key) return // 清除模板仅取消差异高亮，不动勾选
  matrix.applyTemplate(key)
  msgSuccess(`套用模板「${matrix.activeTemplate?.label}」`)
}

function resetToTemplate() {
  matrix.applyTemplate(matrix.templateKey)
  msgSuccess('重置为模板')
}

function onLocate(code) {
  activeTab.value = 'matrix'
  matrix.searchText = code.split(':')[0]
}

function buildDiffHtml() {
  const esc = s => String(s).replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))
  const codeList = codes => `<div style="margin:4px 0 12px;line-height:1.9;color:#4a5568;font-size:12px">${codes.map(esc).join('、')}</div>`
  let html = ''
  if (matrix.addedCodes.length) {
    html += `<div style="color:#2d9f6f;font-weight:600">新增 ${matrix.addedCodes.length} 项</div>${codeList(matrix.addedCodes)}`
  }
  if (matrix.removedCodes.length) {
    html += `<div style="color:#dc3545;font-weight:600">移除 ${matrix.removedCodes.length} 项</div>${codeList(matrix.removedCodes)}`
  }
  if (matrix.legacySelectedCount) {
    html += `<div style="color:#8b6914;font-size:12px">另有 ${matrix.legacySelectedCount} 个已下架旧权限将自动移除</div>`
  }
  return html || '<div>无权限增减</div>'
}

async function savePermissions() {
  try {
    await ElMessageBox.confirm(buildDiffHtml(), `确认变更「${drawerRole.value.label}」的权限？`, {
      dangerouslyUseHTMLString: true,
      confirmButtonText: '确认保存',
      cancelButtonText: '再看看',
      type: 'warning',
      customStyle: { maxWidth: '520px' },
    })
  } catch { return }

  savingPerms.value = true
  try {
    await updateRole(drawerRole.value.id, {
      label: drawerRole.value.label,
      description: drawerRole.value.description || null,
      permission_ids: matrix.selectedIdList,
    })
    msgSuccess('保存')
    drawerVisible.value = false
    fetchList()
  } catch {
    // handled by interceptor
  } finally {
    savingPerms.value = false
  }
}

// ── 删除 ────────────────────────────────────────────
async function handleDelete(row) {
  try {
    await confirmDanger('删除', `角色 ${row.label}`)
  } catch { return }

  try {
    await deleteRole(row.id)
    msgSuccess('删除')
    fetchList()
  } catch {
    // handled by interceptor
  }
}

onMounted(fetchList)
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.form-tip { font-size: 12px; color: var(--text-secondary, #718096); }

/* ── 抽屉框架（对照原型亮色金主题） ── */
.perm-drawer :deep(.el-drawer__body) { padding: 0; }
.drawer-shell {
  display: flex;
  flex-direction: column;
  height: 100%;
}
.drawer-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--border-color, #e2e5ef);
  background: #fafbfe;
  flex-wrap: wrap;
}
.drawer-head .title { font-weight: 700; font-size: 15px; color: var(--text-primary); }
.role-tag {
  font-size: 12px;
  background: var(--color-primary-light, rgba(212, 148, 28, 0.08));
  color: var(--color-primary-hover, #bb8218);
  border: 1px solid var(--gold-line, #f5e0b5);
  border-radius: 14px;
  padding: 3px 12px;
}
.tabs { display: flex; gap: 4px; margin-left: 12px; }
.tab {
  font-size: 13px;
  padding: 7px 16px;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-secondary, #718096);
  border: 1px solid transparent;
  user-select: none;
}
.tab.on {
  background: #fff;
  color: var(--color-primary-hover, #bb8218);
  font-weight: 600;
  border-color: var(--gold-line, #f5e0b5);
}
.sel-count { font-size: 12px; color: var(--text-secondary, #718096); }
.spacer { flex: 1; }

.drawer-body {
  flex: 1;
  overflow: auto;
  padding: 16px 22px;
}

/* ── 差异条 ── */
.diffbar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 11px 22px;
  background: #fafbfe;
  border-top: 1px solid var(--border-color, #e2e5ef);
  font-size: 13px;
  color: var(--text-primary);
}
.diffbar .add { color: var(--color-success, #2d9f6f); font-weight: 700; }
.diffbar .del { color: var(--color-danger, #dc3545); font-weight: 700; }
.diffbar .lg { color: #8b6914; font-size: 12px; }
</style>
