<template>
  <el-dialog :model-value="open" title="工厂到货词表" width="760px" append-to-body @close="$emit('close')">
    <div class="alias-toolbar">
      <el-select v-model="kind" aria-label="词表类别" class="alias-kind">
        <el-option label="工艺" value="process" />
        <el-option label="颜色" value="color" />
        <el-option label="等级" value="grade" />
        <el-option label="待审颜色建议" value="suggestions" />
      </el-select>
      <GlassButton v-if="kind !== 'suggestions'" variant="primary" :disabled="loading" @click="edit(null)">新增词条</GlassButton>
    </div>
    <p v-if="failed" role="alert">词表加载失败 <GlassButton variant="link" @click="load">重试</GlassButton></p>
    <el-table v-else v-loading="loading" :data="rows" max-height="400" border class="list-table" v-sticky-scrollbar>
      <el-table-column prop="factory_term" label="工厂写法" min-width="110" />
      <el-table-column prop="target" label="系统词条" min-width="160" />
      <el-table-column v-if="kind !== 'suggestions'" label="状态" min-width="76">
        <template #default="{ row }">{{ row.enabled ? '启用' : '停用' }}</template>
      </el-table-column>
      <el-table-column label="操作" min-width="150">
        <template #default="{ row }">
          <template v-if="kind === 'suggestions'">
            <GlassButton variant="link" :disabled="saving" @click="review(row, true)">采纳</GlassButton>
            <GlassButton variant="link" :disabled="saving" @click="review(row, false)">驳回</GlassButton>
          </template>
          <GlassButton v-else variant="link" :disabled="saving" @click="edit(row)">编辑</GlassButton>
        </template>
      </el-table-column>
    </el-table>
    <el-form v-if="editing" class="alias-form" label-position="top" @submit.prevent="save">
      <el-form-item label="工厂写法"><el-input v-model="form.factory_term" maxlength="128" /></el-form-item>
      <el-form-item label="系统词条"><el-input v-model="form.target" maxlength="128" /></el-form-item>
      <el-checkbox v-model="form.enabled">启用</el-checkbox>
      <div class="alias-toolbar">
        <GlassButton variant="primary" :loading="saving" :disabled="!form.factory_term.trim() || !form.target.trim()" @click="save">保存</GlassButton>
        <GlassButton :disabled="saving" @click="editing = false">取消</GlassButton>
      </div>
    </el-form>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { factoryInboundApi } from '@/api/factoryInbound'

const props = defineProps({ open: Boolean })
defineEmits(['close'])
const kind = ref('process')
const rows = ref([])
const form = ref({})
const editing = ref(false)
const loading = ref(false)
const saving = ref(false)
const failed = ref(false)
let request = 0

async function load() {
  const current = ++request
  const selected = kind.value
  rows.value = []
  editing.value = false
  loading.value = true
  failed.value = false
  try {
    const result = await (selected === 'suggestions' ? factoryInboundApi.suggestions() : factoryInboundApi.aliases(selected))
    if (current === request) rows.value = result.data
  } catch {
    if (current === request) failed.value = true
  } finally {
    if (current === request) loading.value = false
  }
}
function edit(row) {
  form.value = row ? { ...row } : { factory_term: '', target: '', enabled: true }
  editing.value = true
}
async function save() {
  if (saving.value) return
  const selected = kind.value
  const { id, factory_term, target, enabled } = form.value
  saving.value = true
  try {
    const { data } = await factoryInboundApi.saveAlias(selected, id, { factory_term, target, enabled })
    if (selected === kind.value) {
      rows.value = data
      editing.value = false
    }
  } catch {
    // Shared API feedback preserves the current form on error.
  } finally { saving.value = false }
}
async function review(row, accept) {
  if (saving.value) return
  saving.value = true
  try {
    const { data } = await factoryInboundApi.reviewSuggestion(row.id, accept)
    if (kind.value === 'suggestions') rows.value = data
  } catch {
    // Shared API feedback keeps the suggestion available after failure.
  } finally { saving.value = false }
}
watch([() => props.open, kind], ([open]) => { if (open) load() })
</script>

<style scoped>
.alias-toolbar { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; }
.alias-kind { width: 180px; }
.alias-form { margin-top: 16px; }
</style>
