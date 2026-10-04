<template>
  <div class="role-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="role-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 角色列表 -->
    <div ref="panelRef" class="table-card role-panel">
      <!-- 操作行（本页无筛选区）：主操作 + TableTools（Action Bar Spec） -->
      <div class="action-bar">
        <GlassButton v-permission="'role:write'" variant="primary" left-icon="Plus" @click="openCreateDialog">新增角色</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading" @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

    <ListPageStatus v-if="roleResource.hasData.value" :error="roleResource.errorMessage.value" :loading="roleResource.loading.value" :has-data="roleResource.hasData.value" @retry="reloadRows" />
      <el-table :data="tableData" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640">
      <template #empty><ListPageStatus :error="roleResource.errorMessage.value" :loading="loading" @retry="reloadRows">
        <el-empty :image-size="96" description="暂无数据" />
      </ListPageStatus></template>
      <el-table-column v-if="visibleKeys.includes('name')" prop="name" label="角色标识" min-width="140" max-width="210" show-overflow-tooltip sortable />
      <el-table-column v-if="visibleKeys.includes('label')" prop="label" label="角色名称" min-width="140" max-width="210" show-overflow-tooltip sortable />
      <el-table-column v-if="visibleKeys.includes('description')" prop="description" label="描述" min-width="200" max-width="300" show-overflow-tooltip />
      <el-table-column prop="is_system" v-if="visibleKeys.includes('type')" label="类型" min-width="110" max-width="150">
        <template #default="{ row }">
          <StatusBadge :type="row.is_system ? 'warning' : 'primary'" size="small" effect="plain">{{ row.is_system ? '系统' : '自定义' }}</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('user-count')" prop="user_count" label="用户数" min-width="80" max-width="120" show-overflow-tooltip sortable />
      <el-table-column v-if="visibleKeys.includes('permission-count')" prop="permission_count" label="权限数" min-width="80" max-width="120" show-overflow-tooltip sortable />
      <el-table-column v-if="visibleKeys.includes('created-at')" prop="created_at" label="创建时间" min-width="170" max-width="260" show-overflow-tooltip sortable />
      <el-table-column class-name="table-action-column" label="操作" min-width="220" max-width="300" fixed="right">
        <template #default="{ row }">
          <GlassButton v-permission="'role:write'" variant="link" :disabled="row.name === 'super_admin'" @click="openEditDialog(row)" left-icon="Edit">
            编辑
          </GlassButton>
          <GlassButton v-permission="'role:write'" variant="link" :disabled="row.name === 'super_admin'" @click="openPermDrawer(row)" left-icon="Lock">
            权限
          </GlassButton>
          <GlassButton v-permission="'role:delete'" variant="link" link-tone="danger" :disabled="row.name === 'super_admin' || row.user_count > 0" @click="handleDelete(row)" left-icon="Delete">
            删除
          </GlassButton>
        </template>
      </el-table-column>
    </el-table>
    </div>

    <!-- 新增/编辑基本信息 Dialog -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑角色' : '新增角色'" width="640px">
      <el-form label-position="top" :model="form">
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

    <!-- 权限矩阵：宽详情抽屉 -->
    <DetailDrawer v-model="drawerVisible" width="760px" :with-header="false" class="perm-drawer">
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
          <ListPageStatus :error="matrix.errorMessage" :loading="matrix.loading" @retry="openPermDrawer(drawerRole)" />
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
          <GlassButton variant="primary" :loading="savingPerms" :disabled="matrix.loading || !!matrix.error || !matrix.hasChanges" @click="savePermissions">
            保存（确认变更明细）
          </GlassButton>
        </div>
      </div>
    </DetailDrawer>
  </div>
</template>

<script setup>
import { useAsyncResource } from '@/composables/useAsyncResource'
import { confirmAction, msgSuccess, msgError, confirmDanger } from '@/utils/feedback'
import { ref, onMounted } from 'vue'

import { getRoleList, createRole, updateRole, deleteRole } from '@/api/userManagement'
import { useTableView } from '@/composables/useTableView'
import { ROLE_TEMPLATES } from '@/config/roleTemplates'
import { usePermissionMatrix } from './composables/usePermissionMatrix'
import PermissionMatrixTab from './components/PermissionMatrixTab.vue'
import PermissionNavTab from './components/PermissionNavTab.vue'
import TableTools from '@/components/TableTools.vue'

// 列显隐元数据（TableTools 面板数据源，不驱动列渲染）
const columnDefs = [
  { key: 'name', label: '角色标识' },
  { key: 'label', label: '角色名称' },
  { key: 'description', label: '描述' },
  { key: 'type', label: '类型' },
  { key: 'user-count', label: '用户数' },
  { key: 'permission-count', label: '权限数' },
  { key: 'created-at', label: '创建时间' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('role-management', columnDefs)

const roleResource = useAsyncResource(async (_, { signal }) => (await getRoleList({ signal, suppressToast: true })).data || [], { initialData: [] })
const tableData = roleResource.data
const loading = roleResource.loading
const reloadRows = () => roleResource.load()
const saving = ref(false)

// ── 列表查询 ────────────────────────────────────────
const fetchList = reloadRows

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

let permissionDrawerRequest = 0
async function openPermDrawer(row) {
  const request = ++permissionDrawerRequest
  matrix.initSelection([])
  drawerRole.value = row
  activeTab.value = 'matrix'
  drawerVisible.value = true
  if (!matrix.allPerms.length && !await matrix.loadPermissions()) return false
  if (request !== permissionDrawerRequest || !drawerVisible.value || drawerRole.value?.id !== row.id) return false
  matrix.initSelection(row.permission_ids || [])
  return true
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
  if (matrix.loading || matrix.error) return
  try {
    await confirmAction(buildDiffHtml(), `确认变更「${drawerRole.value.label}」的权限？`, {
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
/* 极光层（.lg-aurora，与工作台同源）定位上下文 */
.role-page {
  position: relative;
}

/* 极光外溢一圈，盖住 main-content 的 24/28 padding 环（同工作台） */
.role-aurora {
  inset: -24px -28px;
}

/* 内容压到极光之上。必须点名内容块，不能用 > :not(.lg-aurora)——
   el-dialog/el-drawer 默认就地渲染，通配会覆盖 .el-overlay 的 position: fixed */
.role-page .role-panel {
  position: relative;
  z-index: 1;
}

.form-tip { font-size: 12px; color: var(--text-secondary, #718096); }

/* 表格面板：同款渐变玻璃（scoped 覆盖全局 .table-card 的白底） */
.role-panel {
  border: 1px solid var(--dash-glass-border);
  border-radius: var(--dash-card-radius);
  background: var(--dash-glass-bg);
  box-shadow: var(--dash-glass-shadow), var(--dash-glass-highlight);
}

/* 表格融进玻璃：行/表头半透明，透出极光；hover 用更实的白 */
.role-panel :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(255, 255, 255, 0.5);
  --el-table-row-hover-bg-color: rgba(255, 255, 255, 0.7);
  background: transparent;
}

/* 右侧固定操作列：磨砂但不透明的暖白，表头/hover 态同步 */
.role-panel :deep(.el-table-fixed-column--right) {
  background-color: rgba(249, 244, 234, 0.97);
}
.role-panel :deep(th.el-table-fixed-column--right) {
  background-color: rgba(246, 239, 226, 0.98);
}
.role-panel :deep(.el-table__body tr:hover > td.el-table-fixed-column--right) {
  background-color: rgba(245, 236, 220, 0.98);
}

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
