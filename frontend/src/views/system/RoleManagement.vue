<template>
  <div>
    <!-- 操作栏 -->
    <el-row :gutter="16" class="toolbar">
      <el-col :span="24">
        <el-button type="primary" @click="openCreateDialog"><el-icon><Plus /></el-icon> 新增角色</el-button>
      </el-col>
    </el-row>

    <!-- 表格 -->
    <el-table ref="tableRef" :data="tableData" v-loading="loading" stripe border style="width: 100%" :max-height="maxHeight">
      <el-table-column prop="name" label="角色标识" width="140" />
      <el-table-column prop="label" label="角色名称" width="140" />
      <el-table-column prop="description" label="描述" min-width="200" show-overflow-tooltip />
      <el-table-column label="类型" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="row.is_system ? 'warning' : 'primary'" size="small">{{ row.is_system ? '系统' : '自定义' }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column prop="user_count" label="用户数" width="80" align="center" />
      <el-table-column prop="permission_count" label="权限数" width="80" align="center" />
      <el-table-column prop="created_at" label="创建时间" width="170" />
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" :disabled="row.is_system" @click="openEditDialog(row)">
            <el-icon><Edit /></el-icon> 编辑
          </el-button>
          <el-button link type="danger" :disabled="row.is_system || row.user_count > 0" @click="handleDelete(row)">
            <el-icon><Delete /></el-icon> 删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- 新增/编辑 Dialog -->
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
        <el-form-item label="权限分配">
          <div v-if="permissionGroups.length" class="permission-groups">
            <div v-for="group in permissionGroups" :key="group.module" class="perm-group">
              <div class="perm-module">{{ moduleLabelMap[group.module] || group.module }}</div>
              <el-checkbox-group v-model="form.permission_ids">
                <el-checkbox
                  v-for="perm in group.permissions"
                  :key="perm.id"
                  :value="perm.id"
                >{{ perm.label }}</el-checkbox>
              </el-checkbox-group>
            </div>
          </div>
          <el-empty v-else description="加载权限中..." :image-size="40" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="submitForm">确定</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getRoleList, createRole, updateRole, deleteRole, getPermissionList,
} from '@/api/userManagement'
import { useTableMaxHeight } from '@/composables/useTableMaxHeight'

const { tableRef, maxHeight } = useTableMaxHeight()

const tableData = ref([])
const loading = ref(false)
const saving = ref(false)

const moduleLabelMap = {
  user: '用户管理',
  commission: '提成管理',
  tracking: '物流跟踪',
  design: '设计预约',
  system: '系统管理',
}

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

// ── 权限列表 ────────────────────────────────────────
const permissionGroups = ref([])
async function fetchPermissions() {
  try {
    const res = await getPermissionList()
    permissionGroups.value = res.data || []
  } catch {
    permissionGroups.value = []
  }
}

// ── 新增 / 编辑 ────────────────────────────────────
const dialogVisible = ref(false)
const isEdit = ref(false)
const editRoleId = ref(null)
const form = ref({ name: '', label: '', description: '', permission_ids: [] })

function openCreateDialog() {
  isEdit.value = false
  editRoleId.value = null
  form.value = { name: '', label: '', description: '', permission_ids: [] }
  fetchPermissions()
  dialogVisible.value = true
}

function openEditDialog(row) {
  isEdit.value = true
  editRoleId.value = row.id
  form.value = {
    name: row.name,
    label: row.label,
    description: row.description || '',
    permission_ids: [...(row.permission_ids || [])],
  }
  fetchPermissions()
  dialogVisible.value = true
}


async function submitForm() {
  if (!form.value.label) {
    ElMessage.warning('请填写角色名称')
    return
  }
  if (!isEdit.value && !form.value.name) {
    ElMessage.warning('请填写角色标识')
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
      ElMessage.success('更新成功')
    } else {
      await createRole(form.value)
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

// ── 删除 ────────────────────────────────────────────
async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确认删除角色「${row.label}」？`,
      '删除确认',
      { type: 'warning' },
    )
  } catch { return }

  try {
    await deleteRole(row.id)
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

.permission-groups {
  width: 100%;
}
.perm-group {
  margin-bottom: 12px;
  padding: 12px;
  background: #F9F8F6;
  border-radius: 8px;
}
.perm-module {
  font-weight: 600;
  font-size: 13px;
  color: var(--text-primary);
  margin-bottom: 8px;
}
.perm-group .el-checkbox {
  margin-right: 16px;
  margin-bottom: 4px;
}
</style>
