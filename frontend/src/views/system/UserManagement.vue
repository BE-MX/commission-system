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
      </el-col>
    </el-row>

    <!-- 表格 -->
    <div class="table-card">
    <el-table ref="tableRef" :data="tableData" v-loading="loading" border class="list-table" style="width: 100%" :max-height="maxHeight">
      <el-table-column prop="username" label="用户名" min-width="140" max-width="210" show-overflow-tooltip />
      <el-table-column prop="real_name" label="姓名" min-width="120" max-width="180" show-overflow-tooltip />
      <el-table-column prop="email" label="邮箱" min-width="180" max-width="270" show-overflow-tooltip />
      <el-table-column prop="phone" label="手机号" min-width="140" max-width="210" show-overflow-tooltip />
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
      <el-table-column prop="last_login_at" label="最后登录" min-width="170" max-width="260" show-overflow-tooltip />
      <el-table-column label="操作" min-width="280" max-width="420" fixed="right">
        <template #default="{ row }">
          <GlassButton variant="link" left-icon="Edit" @click="openEditDialog(row)">编辑</GlassButton>
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
    <el-dialog v-model="dialogVisible" :title="isEdit ? '编辑用户' : '新增用户'" width="480px">
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
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getUserList, createUser, updateUser, deleteUser,
  resetUserPassword, toggleUserActive, getRoleList,
} from '@/api/userManagement'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

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
    const res = await getUserList({ keyword: keyword.value, page: page.value, page_size: pageSize.value })
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
    role_ids: [],
  }
  fetchRoles()
  // 需要获取当前用户的角色 ID 列表（后端只返回 label）
  // 通过用户名匹配 roleOptions 来还原
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
</script>

<style scoped>
.toolbar { margin-bottom: 16px; }
.pagination { margin-top: 16px; justify-content: flex-end; }
</style>
