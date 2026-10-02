<template>
  <div class="user-page">
    <!-- 金色极光背景（纯装饰；与工作台同源 styles/liquid-glass.css） -->
    <div class="user-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <!-- 表格卡片：筛选区 / 操作行 / 表格 / 分页（List Page Spec / Action Bar Spec） -->
    <div ref="panelRef" class="table-card user-panel">
      <FilterBar :loading="loading" :pending="hasPendingSearch" @search="searchList" @reset="resetFilters">
        <el-input v-model="keyword" clearable placeholder="搜索用户名/姓名" class="filter-w-md">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </FilterBar>

      <div class="action-bar">
        <GlassButton v-permission="'user:write'" variant="primary" left-icon="Plus" @click="openCreateDialog">新增用户</GlassButton>
        <GlassButton v-permission="'user:write'" variant="secondary" left-icon="Connection" :loading="syncingAll" @click="handleSyncAll">批量同步钉钉</GlassButton>
        <TableTools
          v-model:visible-keys="visibleKeys"
          v-model:density="density"
          :columns="columnDefs"
          :fullscreen="isFullscreen"
          :loading="loading" @refresh="fetchList"
          @fullscreen="toggleFullscreen"
        />
      </div>

    <ListPageStatus v-if="hasData && errorMessage" :error="errorMessage" :loading="loading" :has-data="hasData" :data-page="dataPage" @retry="fetchList" />
      <el-table :data="tableData" v-loading="loading" border class="list-table" :class="densityClass" :max-height="isFullscreen ? undefined : 640" @sort-change="changeSort">
      <template #empty><ListPageStatus :error="errorMessage" :loading="loading" @retry="fetchList">
        <el-empty :image-size="96" :description="hasActiveFilters ? '没有符合条件的记录' : '暂无数据'">
          <GlassButton v-if="hasActiveFilters" left-icon="RefreshLeft" @click="resetFilters">重置筛选</GlassButton>
        </el-empty>
      </ListPageStatus></template>
      <el-table-column v-if="visibleKeys.includes('username')" prop="username" label="用户名" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('real-name')" prop="real_name" label="姓名" min-width="120" max-width="180" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('email')" prop="email" label="邮箱" min-width="180" max-width="270" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('phone')" prop="phone" label="手机号" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
      <el-table-column v-if="visibleKeys.includes('dingtalk-bind')" label="钉钉绑定" min-width="120" max-width="180">
        <template #default="{ row }">
          <StatusBadge v-if="row.dingtalk_id" type="success" size="small" effect="plain">已绑定</StatusBadge>
          <StatusBadge v-else type="info" size="small" effect="plain">未绑定</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('roles')" label="角色" min-width="160" max-width="240">
        <template #default="{ row }">
          <StatusBadge v-for="r in row.roles" :key="r" size="small" effect="plain" style="margin-right: 4px">{{ r }}</StatusBadge>
          <span v-if="!row.roles?.length" style="color: var(--text-muted)">未分配</span>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('status')" label="状态" min-width="100" max-width="120">
        <template #default="{ row }">
          <StatusBadge :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">{{ row.is_active ? '正常' : '禁用' }}</StatusBadge>
        </template>
      </el-table-column>
      <el-table-column v-if="visibleKeys.includes('last-login')" prop="last_login_at" label="最后登录" min-width="170" max-width="260" show-overflow-tooltip sortable="custom" />
      <el-table-column class-name="table-action-column" label="操作" min-width="340" max-width="480" fixed="right">
        <template #default="{ row }">
          <GlassButton v-permission="'user:write'" variant="link" left-icon="Edit" @click="openEditDialog(row)">编辑</GlassButton>
          <GlassButton variant="link" left-icon="Lock" @click="openPermPreview(row)">权限</GlassButton>
          <GlassButton v-permission="'user:write'" variant="link" left-icon="Connection" @click="handleSyncDingtalk(row)" :disabled="!row.phone || !!row.dingtalk_id">同步钉钉</GlassButton>
          <GlassButton v-permission="'user:write'" variant="link" left-icon="Key" @click="openResetPwdDialog(row)">重置密码</GlassButton>
          <GlassButton v-permission="'user:write'" variant="link" :link-tone="row.is_active ? 'warning' : 'success'" left-icon="SwitchButton" @click="handleToggleActive(row)">
            {{ row.is_active ? '禁用' : '启用' }}
          </GlassButton>
          <GlassButton v-permission="'user:delete'" variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-model:current-page="page"
      v-model:page-size="pageSize"
      :total="total"
      :page-sizes="[20, 50, 100]"
      layout="total, sizes, prev, pager, next"
      class="pager"
      @current-change="handlePageChange"
      @size-change="handleSizeChange"
    />
    </div>

    <!-- 新增/编辑用户 Dialog -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑用户' : '新增用户'" width="640px">
      <el-form label-position="top" ref="formRef" :model="form">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" placeholder="2-50 个字符" :disabled="isEdit" />
        </el-form-item>
        <el-form-item v-if="!isEdit" label="密码" required>
          <el-input v-model="form.password" type="password" placeholder="至少 6 位" show-password />
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="form.real_name" placeholder="真实姓名" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="选填" />
        </el-form-item>
        <el-form-item label="手机号">
          <el-input v-model="form.phone" placeholder="选填" />
        </el-form-item>
        <el-form-item label="OKKI部门">
          <el-select v-model="form.okki_department_id" clearable filterable placeholder="业绩归属部门（推小满订单必填）" style="width: 100%">
            <el-option v-for="d in deptOptions" :key="d.department_id" :label="d.name" :value="d.department_id" />
          </el-select>
          <div class="form-tip">推送小满订单时的业绩归属部门；业务员必须设置，否则推单被拦截</div>
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.role_ids" multiple placeholder="选择角色" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.id" :label="r.label" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item v-if="isEdit" label="可代创建订单" label-width="120px">
          <el-select
            v-model="form.invoice_delegate_sales_user_ids"
            multiple
            filterable
            collapse-tags
            placeholder="选择该用户可代办的业务员"
            style="width: 100%"
          >
            <el-option
              v-for="user in delegateCandidates"
              :key="user.id"
              :label="`${user.real_name}（${user.username}）${user.okki_bound ? '' : ' · 未绑定OKKI'}${user.okki_department_configured ? '' : ' · 未配置部门'}`"
              :value="user.id"
            />
          </el-select>
          <div class="form-tip">仅授权代录入；客户私海、订单归属和 OKKI 业绩仍属于所选业务员</div>
        </el-form-item>

        <!-- 微信ID（仅编辑模式） -->
        <template v-if="isEdit">
          <el-divider content-position="left">报工配置</el-divider>
          <el-form-item label="微信ID">
            <div style="display: flex; gap: 8px; width: 100%;">
              <el-input v-model="wxIdForm.wx_id" placeholder="微信原始ID（如 oXXXX...）" style="flex:1" />
              <el-button v-permission="'user:write'" type="primary" :loading="savingWxId" @click="saveWxId">保存</el-button>
            </div>
            <div class="form-tip">用于工人扫码报工时身份匹配，由管理员通过测试扫码获取</div>
          </el-form-item>
          <el-form-item label="绑定工序">
            <div style="width: 100%;">
              <el-checkbox-group v-model="bindingForm.process_ids">
                <el-checkbox v-for="p in allProcesses" :key="p.id" :value="p.id">{{ p.name }}</el-checkbox>
              </el-checkbox-group>
              <div v-if="allProcesses.length === 0" style="color: #909399; font-size: 12px;">暂无工序，请先在工序管理页创建</div>
              <div style="margin-top: 8px;">
                <el-button v-permission="'user:write'" type="primary" :loading="savingBindings" @click="saveBindings">保存绑定</el-button>
                <span style="margin-left: 8px; color: #909399; font-size: 12px;">已绑定 {{ bindingForm.process_ids.length }} 个工序</span>
              </div>
            </div>
          </el-form-item>
        </template>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="dialogVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitForm">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- 重置密码 Dialog -->
    <el-dialog v-model="resetPwdVisible" title="重置密码" width="480px">
      <el-form label-position="top" :model="resetPwdForm">
        <el-form-item label="用户">
          <span>{{ resetPwdRow?.real_name }}（{{ resetPwdRow?.username }}）</span>
        </el-form-item>
        <el-form-item label="新密码" required>
          <el-input v-model="resetPwdForm.new_password" type="password" placeholder="至少 6 位" show-password />
        </el-form-item>
        <el-form-item label="确认密码" required>
          <el-input v-model="resetPwdForm.confirm_password" type="password" placeholder="再次输入新密码" show-password />
        </el-form-item>
      </el-form>
      <template #footer>
        <GlassButton variant="ghost" @click="resetPwdVisible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" @click="submitResetPwd">确定</GlassButton>
      </template>
    </el-dialog>

    <!-- 有效权限预览 Drawer（多角色并集 · 只读矩阵） -->
    <UserPermissionDrawer v-model="permPreviewVisible" :user="permPreviewUser" />
  </div>
</template>

<script setup>
import { useListPage } from '@/composables/useListPage'
import { toRef } from 'vue'
import { msgWarning, msgSuccessText, confirmAction, msgError } from '@/utils/feedback'
import { computed, ref, reactive, onMounted } from 'vue'

import {
  getUserList, createUser, updateUser, deleteUser,
  resetUserPassword, toggleUserActive, getRoleList,
  syncUserDingtalk, syncAllUsersDingtalk, getOkkiDepartmentOptions,
  getInvoiceDelegateGrants, updateInvoiceDelegateGrants,
} from '@/api/userManagement'
import { getActiveProcesses, getUserProcessBindings, updateUserProcessBindings, updateUserWxId } from '@/api/production'
import { useTableView } from '@/composables/useTableView'
import { useTableSort } from '@/composables/useTableSort'
import TableTools from '@/components/TableTools.vue'
import UserPermissionDrawer from './components/UserPermissionDrawer.vue'

// 列显隐元数据（TableTools 面板数据源，不驱动列渲染）
const columnDefs = [
  { key: 'username', label: '用户名' },
  { key: 'real-name', label: '姓名' },
  { key: 'email', label: '邮箱' },
  { key: 'phone', label: '手机号' },
  { key: 'dingtalk-bind', label: '钉钉绑定' },
  { key: 'roles', label: '角色' },
  { key: 'status', label: '状态' },
  { key: 'last-login', label: '最后登录' },
]
const { density, densityClass, visibleKeys, panelRef, isFullscreen, toggleFullscreen } = useTableView('user-management', columnDefs)
const orderSort = useTableSort()

const listState = useListPage(async (params, { signal }) => {
  const response = await getUserList(params, { signal, suppressToast: true })
  return { items: response.data.items || [], total: response.data.total || 0 }
}, { searchForm: { keyword: '' } })
const { loading, list: tableData, total, page, pageSize, searchForm, appliedSearchForm, errorMessage, hasData, dataPage, hasPendingSearch, fetchList, handleSearch, handleReset: resetFilters, handlePageChange, handleSizeChange, refreshCreate, refreshUpdate, refreshRemove } = listState
const keyword = toRef(searchForm, 'keyword')
const searchList = handleSearch
function changeSort(event) { orderSort.onSortChange(event); return listState.handleSortChange(orderSort.sortParams.value) }
const saving = ref(false)
const hasActiveFilters = computed(() => Boolean(appliedSearchForm.value.keyword))



// ── 列表查询 ────────────────────────────────────────

// ── 角色选项 ────────────────────────────────────────
const roleOptions = ref([])
async function fetchRoles() {
  try {
    const res = await getRoleList()
    roleOptions.value = res.data || []
  } catch {
    roleOptions.value = []
  }
}

// ── OKKI 部门选项（真实订单聚合，会话内缓存一次）─────
const deptOptions = ref([])
async function fetchDeptOptions() {
  if (deptOptions.value.length) return
  try {
    const res = await getOkkiDepartmentOptions()
    deptOptions.value = res.data?.items || []
  } catch {
    deptOptions.value = []
  }
}

// ── 新增 / 编辑 ────────────────────────────────────
const dialogVisible = ref(false)
const isEdit = ref(false)
const editUserId = ref(null)
const form = ref({ username: '', password: '', real_name: '', email: '', phone: '', okki_department_id: null, role_ids: [], invoice_delegate_sales_user_ids: [] })
const delegateCandidates = ref([])
let delegateLoadSeq = 0

function openCreateDialog() {
  delegateLoadSeq += 1
  isEdit.value = false
  editUserId.value = null
  form.value = { username: '', password: '', real_name: '', email: '', phone: '', okki_department_id: null, role_ids: [], invoice_delegate_sales_user_ids: [] }
  fetchRoles()
  fetchDeptOptions()
  dialogVisible.value = true
}

function openEditDialog(row) {
  isEdit.value = true
  editUserId.value = row.id
  form.value = {
    username: row.username,
    password: '',
    real_name: row.real_name,
    email: row.email || '',
    phone: row.phone || '',
    // ?? 而非 ||：department_id=0（我的企业）是合法部门
    okki_department_id: row.okki_department_id ?? null,
    okki_department_name: row.okki_department_name || '',
    role_ids: row.role_ids || [],
    invoice_delegate_sales_user_ids: [],
  }
  fetchRoles()
  fetchDeptOptions()
  loadInvoiceDelegateGrants(row.id)
  loadProcessBindings(row.id)
  loadAllProcesses()
  dialogVisible.value = true
}

async function loadInvoiceDelegateGrants(userId) {
  const loadSeq = ++delegateLoadSeq
  try {
    const data = await getInvoiceDelegateGrants(userId)
    if (loadSeq !== delegateLoadSeq || editUserId.value !== userId) return
    form.value.invoice_delegate_sales_user_ids = data.sales_user_ids || []
    delegateCandidates.value = data.candidates || []
  } catch {
    if (loadSeq !== delegateLoadSeq || editUserId.value !== userId) return
    form.value.invoice_delegate_sales_user_ids = []
    delegateCandidates.value = []
  }
}

async function submitForm() {
  if (!form.value.real_name) {
    msgWarning('请填写姓名')
    return
  }
  if (!isEdit.value) {
    if (!form.value.username || form.value.username.length < 2) {
      msgWarning('用户名至少 2 个字符')
      return
    }
    if (!form.value.password || form.value.password.length < 6) {
      msgWarning('密码至少 6 位')
      return
    }
  }
  saving.value = true
  try {
    // ?? 而非 ||：department_id=0（我的企业）是合法部门，falsy 判断会把它清成 null
    const deptId = form.value.okki_department_id ?? null
    // 名称快照优先取选项列表；原部门不在列表（历史部门未变更）时沿用既有名称
    const deptName = deptId != null
      ? (deptOptions.value.find(d => d.department_id === deptId)?.name || form.value.okki_department_name || null)
      : null
    if (isEdit.value) {
      await updateUser(editUserId.value, {
        real_name: form.value.real_name,
        email: form.value.email || null,
        phone: form.value.phone || null,
        okki_department_id: deptId,
        okki_department_name: deptName,
        role_ids: form.value.role_ids,
      })
      await updateInvoiceDelegateGrants(editUserId.value, form.value.invoice_delegate_sales_user_ids)
      msgSuccessText('更新成功')
    } else {
      await createUser({
        username: form.value.username,
        password: form.value.password,
        real_name: form.value.real_name,
        email: form.value.email || null,
        phone: form.value.phone || null,
        okki_department_id: deptId,
        okki_department_name: deptName,
        role_ids: form.value.role_ids,
      })
      msgSuccessText('创建成功')
    }
    dialogVisible.value = false
    await (isEdit.value ? refreshUpdate() : refreshCreate())
  } catch {
    // handled by interceptor
  } finally {
    saving.value = false
  }
}

// ── 重置密码 ────────────────────────────────────────
const resetPwdVisible = ref(false)
const resetPwdRow = ref(null)
const resetPwdForm = ref({ new_password: '', confirm_password: '' })

function openResetPwdDialog(row) {
  resetPwdRow.value = row
  resetPwdForm.value = { new_password: '', confirm_password: '' }
  resetPwdVisible.value = true
}

async function submitResetPwd() {
  if (!resetPwdForm.value.new_password || resetPwdForm.value.new_password.length < 6) {
    msgWarning('密码至少 6 位')
    return
  }
  if (resetPwdForm.value.new_password !== resetPwdForm.value.confirm_password) {
    msgWarning('两次输入的密码不一致')
    return
  }
  saving.value = true
  try {
    await resetUserPassword(resetPwdRow.value.id, { new_password: resetPwdForm.value.new_password })
    msgSuccessText('密码已重置')
    resetPwdVisible.value = false
  } catch {
    // handled by interceptor
  } finally {
    saving.value = false
  }
}

// ── 启用/禁用 ───────────────────────────────────────
async function handleToggleActive(row) {
  const action = row.is_active ? '禁用' : '启用'
  try {
    await confirmAction(`确认${action}用户「${row.real_name}」？`, '确认', { type: 'warning' })
  } catch { return }

  try {
    const res = await toggleUserActive(row.id)
    row.is_active = res.data.is_active
    msgSuccessText(`已${action}`)
  } catch {
    // handled by interceptor
  }
}

// ── 删除 ────────────────────────────────────────────
async function handleDelete(row) {
  try {
    await confirmAction(
      `确认删除用户「${row.real_name}」？此操作不可恢复。`,
      '删除确认',
      { type: 'warning' },
    )
  } catch { return }

  try {
    await deleteUser(row.id)
    msgSuccessText('删除成功')
    refreshRemove()
  } catch {
    // handled by interceptor
  }
}



// ── 有效权限预览 ────────────────────────────────────
const permPreviewVisible = ref(false)
const permPreviewUser = ref(null)

function openPermPreview(row) {
  permPreviewUser.value = row
  permPreviewVisible.value = true
}

// ── 工序绑定 + 微信ID（编辑模式附加） ─────────────────
const allProcesses = ref([])
const bindingForm = reactive({ process_ids: [] })
const savingBindings = ref(false)
const wxIdForm = reactive({ wx_id: '' })
const savingWxId = ref(false)

async function loadAllProcesses() {
  try {
    const data = await getActiveProcesses()
    allProcesses.value = Array.isArray(data) ? data : (data.data || [])
  } catch { allProcesses.value = [] }
}

async function loadProcessBindings(userId) {
  try {
    const res = await getUserProcessBindings(userId)
    // productionClient 拦截器已解包 response.data，直接拿到 {user_id, bindings}
    const payload = res.data || res
    bindingForm.process_ids = (payload.bindings || []).map(b => b.process_id)
    // 同时加载微信ID
    const row = tableData.value.find(r => r.id === userId)
    wxIdForm.wx_id = row?.wx_id || ''
  } catch {
    bindingForm.process_ids = []
    wxIdForm.wx_id = ''
  }
}

async function saveBindings() {
  savingBindings.value = true
  try {
    await updateUserProcessBindings(editUserId.value, bindingForm.process_ids)
    msgSuccessText(`已绑定 ${bindingForm.process_ids.length} 个工序`)
  } catch (e) {
    msgError(e.response?.data?.detail || '保存失败', e)
  } finally {
    savingBindings.value = false
  }
}

async function saveWxId() {
  savingWxId.value = true
  try {
    await updateUserWxId(editUserId.value, wxIdForm.wx_id || null)
    msgSuccessText('微信ID已保存')
    refreshUpdate()
  } catch (e) {
    msgError(e.response?.data?.detail || '保存失败', e)
  } finally {
    savingWxId.value = false
  }
}

// ── 同步钉钉 ────────────────────────────────────────
const syncingAll = ref(false)

async function handleSyncDingtalk(row) {
  try {
    const res = await syncUserDingtalk(row.id)
    if (res.code === 200) {
      msgSuccessText(res.message)
      row.dingtalk_id = res.data.dingtalk_id
    } else {
      msgWarning(res.message)
    }
  } catch {
    // handled by interceptor
  }
}

async function handleSyncAll() {
  syncingAll.value = true
  try {
    const res = await syncAllUsersDingtalk()
    if (res.code === 200) {
      msgSuccessText(res.message)
      refreshUpdate()
    } else {
      msgWarning(res.message)
    }
  } catch {
    // handled by interceptor
  } finally {
    syncingAll.value = false
  }
}
</script>

<style scoped src="./user-management.css"></style>
