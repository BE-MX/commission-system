<template>
  <el-dialog
    :model-value="modelValue"
    :title="`成员权限 · ${library?.name || ''}`"
    width="min(620px, calc(100vw - 32px))"
    :close-on-click-modal="!saving"
    :close-on-press-escape="!saving"
    :show-close="!saving"
    @update:model-value="$emit('update:modelValue', $event)"
    @closed="$emit('closed')"
  >
    <div class="member-add">
      <el-select
        :key="library?.id || 'closed'"
        :model-value="candidateUserId"
        aria-label="搜索并选择方舟成员"
        filterable remote clearable reserve-keyword
        :remote-method="query => $emit('search', query)"
        :loading="searchLoading"
        :disabled="saving"
        placeholder="输入方舟用户名或姓名搜索"
        @update:model-value="$emit('update:candidateUserId', $event)"
      >
        <el-option
          v-for="candidate in candidates"
          :key="candidate.user_id"
          :value="candidate.user_id"
          :label="candidate.real_name ? `${candidate.username} · ${candidate.real_name}` : candidate.username"
        >
          <span class="candidate-username">{{ candidate.username }}</span>
          <span v-if="candidate.real_name" class="candidate-real-name">{{ candidate.real_name }}</span>
        </el-option>
      </el-select>
      <GlassButton variant="ghost" :disabled="!candidateUserId || saving" @click="$emit('add')">添加成员</GlassButton>
    </div>
    <div class="member-table">
      <el-empty v-if="!members.length" description="暂无已配置成员" :image-size="72" />
      <div
        v-for="(member, index) in members"
        :key="member.user_id"
        class="member-row"
        :class="{ 'member-row-invalid': invalidUserIds.includes(member.user_id) }"
      >
        <div class="member-identity">
          <span class="member-username">{{ member.username }}</span>
          <span class="member-real-name">{{ member.real_name || '未设置姓名' }}</span>
          <span v-if="invalidUserIds.includes(member.user_id)" class="member-invalid">账号已停用或删除，请移除后重试</span>
        </div>
        <el-select
          v-model="member.role"
          :aria-label="`设置 ${member.username} 的权限`"
          :disabled="saving || isProtected(member) || invalidUserIds.includes(member.user_id)"
        >
          <el-option label="只读" value="viewer" /><el-option label="编辑" value="editor" />
          <el-option label="审核" value="reviewer" /><el-option label="管理" value="admin" />
        </el-select>
        <span v-if="isProtected(member)" class="actor-lock">当前账号，管理员权限不可移除</span>
        <GlassButton v-else variant="link" link-tone="danger" :disabled="saving" @click="$emit('remove', index)">移除</GlassButton>
      </div>
    </div>
    <template #footer>
      <GlassButton variant="ghost" :disabled="saving" @click="$emit('update:modelValue', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" @click="$emit('save')">保存权限</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
const props = defineProps({
  modelValue: Boolean,
  library: { type: Object, default: null },
  members: { type: Array, default: () => [] },
  candidates: { type: Array, default: () => [] },
  candidateUserId: { type: Number, default: null },
  invalidUserIds: { type: Array, default: () => [] },
  protectedUserId: { type: Number, default: null },
  searchLoading: Boolean,
  saving: Boolean,
})
defineEmits(['update:modelValue', 'update:candidateUserId', 'closed', 'search', 'add', 'remove', 'save'])

function isProtected(member) {
  return member.role === 'admin' && props.protectedUserId === Number(member.user_id)
}
</script>

<style scoped>
.member-add { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 10px; }
.candidate-username { color: var(--text-primary); }
.candidate-real-name { margin-left: 8px; color: var(--text-secondary); font-size: 12px; }
.member-table { display: grid; max-height: 360px; gap: 8px; margin: 16px 0; overflow-y: auto; }
.member-row { display: grid; grid-template-columns: minmax(0, 1fr) 150px auto; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: var(--radius-md, 10px); }
.member-row-invalid { border-color: var(--color-danger); background: var(--color-danger-bg); }
.member-identity { display: grid; min-width: 0; gap: 3px; }
.member-username { overflow: hidden; color: var(--text-primary); font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
.member-real-name { overflow: hidden; color: var(--text-secondary); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.member-invalid { color: var(--color-danger); font-size: 12px; line-height: 1.4; }
.actor-lock { max-width: 150px; color: var(--text-secondary); font-size: 12px; line-height: 1.4; }
@media (max-width: 640px) { .member-add, .member-row { grid-template-columns: minmax(0, 1fr); } .actor-lock { max-width: none; } }
</style>
