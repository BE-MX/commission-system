<template>
  <el-form-item label="在 AI 工作台中使用">
    <el-switch :model-value="enabled" :disabled="!parameters || disabled" @update:model-value="update('enabled', $event)" />
    <div class="form-hint">仅开放已验证可用的直连聊天模型。未开放的业务预设不会出现在员工的模型列表。</div>
  </el-form-item>
  <template v-if="enabled && !disabled">
    <el-form-item label="聊天显示名称">
      <el-input :model-value="parameters?.chat?.label || ''" maxlength="128" placeholder="留空使用模型名称" @update:model-value="update('label', $event)" />
    </el-form-item>
    <el-form-item label="支持理解图片">
      <el-switch :model-value="parameters?.chat?.vision ?? (presetName === 'customer_ai_chat')" @update:model-value="update('vision', $event)" />
    </el-form-item>
    <el-form-item label="可用角色">
      <el-select :model-value="parameters?.chat?.allowed_roles || []" multiple filterable :loading="loading" placeholder="所有具有聊天权限的角色" class="role-picker" @update:model-value="update('allowed_roles', $event)">
        <el-option v-for="role in roles" :key="role.name" :value="role.name" :label="role.label" />
      </el-select>
      <div v-if="error" class="form-hint" role="alert">{{ error }} <el-button link @click="loadRoles">重试</el-button></div>
    </el-form-item>
  </template>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { listChatRoles } from '@/api/aiChat'
import { parseConfig } from '../aiConfigFields'
const props = defineProps({ modelValue: { type: String, default: '{}' }, presetName: { type: String, default: '' }, disabled: Boolean })
const emit = defineEmits(['update:modelValue'])
const parameters = computed(() => parseConfig(props.modelValue))
const enabled = computed(() => parameters.value?.chat?.enabled ?? (props.presetName === 'customer_ai_chat'))
const roles = ref([])
const loading = ref(false)
const error = ref('')
function update(key, value) {
  if (!parameters.value) return
  emit('update:modelValue', JSON.stringify({ ...parameters.value, chat: { ...parameters.value.chat, [key]: value } }, null, 2))
}
async function loadRoles() {
  loading.value = true
  error.value = ''
  try { roles.value = (await listChatRoles()).data?.items || [] }
  catch { error.value = '角色列表加载失败，原有范围已保留。' }
  finally { loading.value = false }
}
onMounted(loadRoles)
</script>

<style scoped>
.role-picker { width: 100%; }
</style>
