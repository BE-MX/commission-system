<template>
  <div>
    <!-- 搜索栏 -->
    <el-row :gutter="16" class="toolbar">
      <el-col :span="8">
        <el-input v-model="keyword" placeholder="搜索用户名/姓名" clearable @keyup.enter="fetchList" @clear="fetchList">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </el-col>
      <el-col :span="16">
        <GlassButton left-icon="Search" @click="fetchList">查询</GlassButton>
        <GlassButton variant="primary" left-icon="Plus" @click="openCreateDialog">新增用户</GlassButton>
        <GlassButton left-icon="Connection" :loading="syncingAll" @click="handleSyncAll">批量同步钉钉</GlassButton>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <div class="table-card">
    <el-table ref="tableRef" :data="tableData" v-loading="loading" border class="list-table" style="width: 100%" :max-height="maxHeight" @sort-change="orderSort.onSortChange">
      <el-table-column prop="username" label="用户名" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
      <el-table-column prop="real_name" label="姓名" min-width="120" max-width="180" show-overflow-tooltip sortable="custom" />
      <el-table-column prop="email" label="邮箱" min-width="180" max-width="270" show-overflow-tooltip sortable="custom" />
      <el-table-column prop="phone" label="手机号" min-width="140" max-width="210" show-overflow-tooltip sortable="custom" />
      <el-table-column label="钉钉绑定" min-width="120" max-width="180">
        <template #default="{ row }">
          <el-tag v-if="row.dingtalk_id" type="success" size="small" effect="plain">已绑定</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">未绑定</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="角色" min-width="160" max-width="240">
        <template #default="{ row }">
          <el-tag v-for="r in row.roles" :key="r" size="small" effect="plain" style="margin-right: 4px">{{ r }}</el-tag>
          <span v-if="!row.roles?.length" style="color: var(--text-muted)">未分配</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" min-width="80" max-width="120">
        <template #default="{ row }">
          <el-tag :type="row.is_active ? 'success' : 'danger'" size="small" effect="plain">{{ row.is_active ? '正常' : '禁用' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="last_login_at" label="最后登录" min-width="170" max-width="260" show-overflow-tooltip sortable="custom" />
      <el-table-column label="操作" min-width="340" max-width="480" fixed="right">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="Edit" @click="openEditDialog(row)">编辑</GlassButton>
          <GlassButton variant="link" left-icon="Connection" @click="handleSyncDingtalk(row)" :disabled="!row.phone || !!row.dingtalk_id">同步钉钉</GlassButton>
          <GlassButton variant="link" left-icon="Key" @click="openResetPwdDialog(row)">重置密码</GlassButton>
          <GlassButton variant="link" :link-tone="row.is_active ? '' : 'success'" left-icon="SwitchButton" @click="handleToggleActive(row)">
            {{ row.is_active ? '禁用' : '启用' }}
          </GlassButton>
          <GlassButton variant="link" link-tone="danger" left-icon="Delete" @click="handleDelete(row)">删除</GlassButton>
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

    <!-- 新增/编辑用户 Dialog -->
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑用户' : '新增用户'" width="560px">
      <el-form ref="formRef" :model="form" label-width="80px">
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
        <el-form-item label="角色">
          <el-select v-model="form.role_ids" multiple placeholder="选择角色" style="width: 100%">
            <el-option v-for="r in roleOptions" :key="r.id" :label="r.label" :value="r.id" />
          </el-select>
        </el-form-item>

        <!-- 微信ID（仅编辑模式） -->
        <template v-if="isEdit">
          <el-divider content-position="left">报工配置</el-divider>
          <el-form-item label="微信ID">
            <div style="display: flex; gap: 8px; width: 100%;">
              <el-input v-model="wxIdForm.wx_id" placeholder="微信原始ID（如 oXXXX...）" style="flex:1" />
              <el-button type="primary" size="small" :loading="savingWxId" @click="saveWxId">保存</el-button>
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
                <el-button type="primary" size="small" :loading="savingBindings" @click="saveBindings">保存绑定</el-button>
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
    <el-dialog v-model="resetPwdVisible" title="重置密码" width="420px">
      <el-form :model="resetPwdForm" label-width="100px">
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
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getUserList, createUser, updateUser, deleteUser,
  resetUserPassword, toggleUserActive, getRoleList,
  syncUserDingtalk, syncAllUsersDingtalk,
} from '@/api/userManagement'
import { getActiveProcesses, getUserProcessBindings, updateUserProcessBindings, updateUserWxId } from '@/api/production'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'
import { useTableSort } from '@/composables/useTableSort'

const { tableRef, maxHeight } = useTableMaxHeight()
const orderSort = useTableSort()

const keyword = ref('')
const page = ref(1)
const pageSize = ref(20)
const total = ref(0)
const tableData = ref([])
const loading = ref(false)
const saving = ref(false)

// ── 列表查询 ────────────────────────────────────────
async function fetchList() {
  loading.value = true
  try {
    const res = await getUserList({ keyword: keyword.value, page: page.value, page_size: pageSize.value, ...orderSort.sortParams.value })
    tableData.value = res.data.items
    total.value = res.data.total
  } finally {
    loading.value = false
  }
}

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

// ── 新增 / 编辑 ────────────────────────────────────
const dialogVisible = ref(false)
const isEdit = ref(false)
const editUserId = ref(null)
const form = ref({ username: '', password: '', real_name: '', email: '', phone: '', role_ids: [] })

function openCreateDialog() {
  isEdit.value = false
  editUserId.value = null
  form.value = { username: '', password: '', real_name: '', email: '', phone: '', role_ids: [] }
  fetchRoles()
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
    role_ids: row.role_ids || [],
  }
  fetchRoles()
  loadProcessBindings(row.id)
  loadAllProcesses()
  dialogVisible.value = true
}

async function submitForm() {
  if (!form.value.real_name) {
    ElMessage.warning('请填写姓名')
    return
  }
  if (!isEdit.value && (!form.value.username || !form.value.password)) {
    ElMessage.warning('请填写用户名和密码')
    return
  }
  saving.value = true
  try {
    if (isEdit.value) {
      await updateUser(editUserId.value, {
        real_name: form.value.real_name,
        email: form.value.email || null,
        phone: form.value.phone || null,
        role_ids: form.value.role_ids,
      })
      ElMessage.success('更新成功')
    } else {
      await createUser(form.value)
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    fetchList()
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
    ElMessage.warning('密码至少 6 位')
    return
  }
  if (resetPwdForm.value.new_password !== resetPwdForm.value.confirm_password) {
    ElMessage.warning('两次输入的密码不一致')
    return
  }
  saving.value = true
  try {
    await resetUserPassword(resetPwdRow.value.id, { new_password: resetPwdForm.value.new_password })
    ElMessage.success('密码已重置')
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
    await ElMessageBox.confirm(`确认${action}用户「${row.real_name}」？`, '确认', { type: 'warning' })
  } catch { return }

  try {
    const res = await toggleUserActive(row.id)
    row.is_active = res.data.is_active
    ElMessage.success(`已${action}`)
  } catch {
    // handled by interceptor
  }
}

// ── 删除 ────────────────────────────────────────────
async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除用户「${row.real_name}」？此操作不可恢复。`,
      '删除确认',
      { type: 'warning' },
    )
  } catch { return }

  try {
    await deleteUser(row.id)
    ElMessage.success('删除成功')
    fetchList()
  } catch {
    // handled by interceptor
  }
}

onMounted(fetchList)

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
    ElMessage.success(`已绑定 ${bindingForm.process_ids.length} 个工序`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingBindings.value = false
  }
}

async function saveWxId() {
  savingWxId.value = true
  try {
    await updateUserWxId(editUserId.value, wxIdForm.wx_id || null)
    ElMessage.success('微信ID已保存')
    fetchList()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
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
      ElMessage.success(res.message)
      row.dingtalk_id = res.data.dingtalk_id
    } else {
      ElMessage.warning(res.message)
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
      ElMessage.success(res.message)
      fetchList()
    } else {
      ElMessage.warning(res.message)
    }
  } catch {
    // handled by interceptor
  } finally {
    syncingAll.value = false
  }
}
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
.form-tip { font-size: 12px; color: #909399; margin-top: 4px; line-height: 1.4; }
</style>
