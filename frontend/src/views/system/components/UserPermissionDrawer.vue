<template>
  <el-drawer :model-value="modelValue" size="80%" :with-header="false" class="perm-drawer" @update:model-value="v => $emit('update:modelValue', v)">
    <div class="drawer-shell">
      <div class="drawer-head">
        <span class="title">有效权限预览</span>
        <span class="user-tag">{{ user?.real_name || user?.username }}</span>
        <span class="roles-line">
          角色：
          <template v-if="userRoles.length">
            <el-tag v-for="r in userRoles" :key="r.id" size="small" effect="plain" class="role-item">{{ r.label }}</el-tag>
            <span class="hint">（多角色并集生效 · 共 {{ matrix.selectedCount }} 项权限）</span>
          </template>
          <span v-else class="hint">未分配角色，无任何权限</span>
        </span>
        <div class="spacer" />
        <el-input v-model="matrix.searchText" placeholder="搜索模块 / 权限…" clearable style="width: 200px">
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
      </div>
      <div class="drawer-body" v-loading="loading || matrix.loading">
        <PermissionMatrixTab :matrix="matrix" />
      </div>
    </div>
  </el-drawer>
</template>

<script setup>
import { ref, watch } from 'vue'
import { getRoleList } from '@/api/userManagement'
import { usePermissionMatrix } from '../composables/usePermissionMatrix'
import PermissionMatrixTab from './PermissionMatrixTab.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  /** 用户行数据（需含 role_ids；缺失时按 roles 名称匹配） */
  user: { type: Object, default: null },
})
defineEmits(['update:modelValue'])

const matrix = usePermissionMatrix({ readonly: true })
const loading = ref(false)
const userRoles = ref([])

watch(() => props.modelValue, async (open) => {
  if (!open || !props.user) return
  loading.value = true
  try {
    if (!matrix.allPerms.length) await matrix.loadPermissions()
    const res = await getRoleList()
    const roles = res.data || []
    const roleIds = (props.user.role_ids || []).map(Number)
    userRoles.value = roleIds.length
      ? roles.filter(r => roleIds.includes(Number(r.id)))
      : roles.filter(r => (props.user.roles || []).includes(r.name) || (props.user.roles || []).includes(r.label))
    // 多角色权限并集
    const union = new Set()
    userRoles.value.forEach(r => (r.permission_ids || []).forEach(id => union.add(Number(id))))
    matrix.initSelection([...union])
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.perm-drawer :deep(.el-drawer__body) { padding: 0; }
.drawer-shell { display: flex; flex-direction: column; height: 100%; }
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
.user-tag {
  font-size: 12px;
  background: var(--color-primary-light, rgba(212, 148, 28, 0.08));
  color: var(--color-primary-hover, #bb8218);
  border: 1px solid var(--gold-line, #f5e0b5);
  border-radius: 14px;
  padding: 3px 12px;
}
.roles-line { font-size: 12px; color: var(--text-secondary, #718096); display: flex; align-items: center; gap: 4px; flex-wrap: wrap; }
.role-item { margin-right: 2px; }
.hint { color: var(--text-secondary, #718096); }
.spacer { flex: 1; }
.drawer-body { flex: 1; overflow: auto; padding: 16px 22px; }
</style>
