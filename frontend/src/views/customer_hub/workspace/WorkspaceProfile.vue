<template>
  <div class="workspace-profile">
    <section class="lg-card panel">
      <h3>普通字段修订 <span class="hint">治理字段（身份/归属/DNC/风险）走变更提案</span></h3>
      <el-form label-width="96px" size="small" @submit.prevent>
        <el-form-item label="字段">
          <el-select v-model="form.field_key" placeholder="选择字段" style="width: 260px">
            <el-option v-for="key in PROFILE_FIELD_WHITELIST" :key="key" :value="key" :label="PROFILE_FIELD_LABELS[key]" />
          </el-select>
        </el-form-item>
        <el-form-item label="新值">
          <el-input v-model="form.value" placeholder="依据客户确认填写" style="width: 320px" />
        </el-form-item>
        <el-form-item label="依据">
          <el-input v-model="form.reason" type="textarea" :rows="2" placeholder="为什么这样修改" style="width: 320px" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="saving" v-permission="'customer_profile:write'" @click="submitRevision">保存修订</el-button>
          <el-button @click="loadAll">刷新</el-button>
        </el-form-item>
      </el-form>
      <el-alert v-if="conflictInfo" :title="conflictInfo" type="warning" :closable="false" show-icon />
    </section>

    <section class="lg-card panel">
      <h3>AI 建议审核</h3>
      <el-empty v-if="!suggestions.length" description="暂无待处理建议" :image-size="60" />
      <el-table class="list-table" v-else :data="suggestions" size="small" border>
        <el-table-column prop="field_key" label="字段" min-width="140" show-overflow-tooltip />
        <el-table-column prop="value" label="建议值" min-width="110" show-overflow-tooltip />
        <el-table-column prop="confidence" label="置信" min-width="70" />
        <el-table-column prop="status" label="状态" min-width="90" />
        <el-table-column label="操作" min-width="230" class-name="table-action-column" fixed="right">
          <template #default="{ row }">
            <template v-if="row.status === 'pending' || row.status === 'deferred'">
              <GlassButton variant="link" @click="decide(row, 'accept')">采纳</GlassButton>
              <GlassButton variant="link" @click="decide(row, 'edit_accept')">编辑采纳</GlassButton>
              <GlassButton variant="link" @click="decide(row, 'reject')">驳回</GlassButton>
            </template>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <section class="lg-card panel">
      <h3>修订历史</h3>
      <el-table class="list-table" :data="revisions" size="small" border>
        <el-table-column prop="field_key" label="字段" min-width="140" show-overflow-tooltip />
        <el-table-column prop="value" label="修订值" min-width="110" show-overflow-tooltip />
        <el-table-column prop="reason" label="依据" min-width="160" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" min-width="170" />
      </el-table>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import {
  createProfileRevision, decideProfileSuggestion,
  listProfileRevisions, listProfileSuggestions,
} from '@/api/customerHub'
import { msgSuccess, confirmDanger } from '@/utils/feedback'
import {
  PROFILE_FIELD_LABELS, PROFILE_FIELD_WHITELIST,
  buildProfileRevisionPayload, buildSuggestionDecisionPayload, isVersionConflict,
} from '../customerWorkspaceController'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const form = reactive({ field_key: '', value: '', reason: '' })
const suggestions = ref([])
const revisions = ref([])
const saving = ref(false)
const conflictInfo = ref('')
const idemPrefix = () => `profile-${props.customerId}-${Date.now()}`

async function loadAll() {
  conflictInfo.value = ''
  try {
    const [suggestionRes, revisionRes] = await Promise.all([
      listProfileSuggestions(props.customerId, {}),
      listProfileRevisions(props.customerId, {}),
    ])
    suggestions.value = suggestionRes.data?.items ?? []
    revisions.value = revisionRes.data?.items ?? []
  } catch { /* 拦截器已提示 */ }
}

async function submitRevision() {
  saving.value = true
  conflictInfo.value = ''
  try {
    const profile = props.customer
    const payload = buildProfileRevisionPayload(form, {
      expected_profile_version_id: profile?.current_profile_version_id ?? profile?.profile_version_id,
      expected_profile_input_seq: profile?.profile_input_seq,
    })
    await createProfileRevision(props.customerId, payload, idemPrefix())
    msgSuccess('修订已保存并生成新档案版本')
    form.value = ''
    form.reason = ''
    await loadAll()
  } catch (error) {
    if (isVersionConflict(error)) {
      conflictInfo.value = '档案已有他人更新，已保留你的输入；请刷新确认后再提交'
    }
  } finally {
    saving.value = false
  }
}

async function decide(row, operation) {
  let value
  if (operation === 'edit_accept') {
    value = window.prompt('编辑后采纳：确认修订值', String(row.value ?? ''))
    if (value == null || !String(value).trim()) return
  }
  const versions = {
    expected_suggestion_version: row.suggestion_version,
    expected_profile_version_id: props.customer?.current_profile_version_id ?? props.customer?.profile_version_id,
    expected_profile_input_seq: props.customer?.profile_input_seq,
  }
  if (operation === 'reject') {
    const reason = window.prompt('驳回原因（必填）', '')
    if (!reason || !reason.trim()) return
    try {
      await decideProfileSuggestion(row.id, buildSuggestionDecisionPayload(operation, { reason }, versions), `suggestion-${row.id}-${Date.now()}`)
      msgSuccess('已驳回')
      await loadAll()
    } catch { /* 拦截器已提示 */ }
    return
  }
  try {
    await decideProfileSuggestion(row.id, buildSuggestionDecisionPayload(operation, { value }, versions), `suggestion-${row.id}-${Date.now()}`)
    msgSuccess('已采纳')
    await loadAll()
  } catch (error) {
    if (isVersionConflict(error)) conflictInfo.value = '档案版本已变化，请刷新后重新确认'
  }
}

onMounted(loadAll)
</script>

<style scoped>
.workspace-profile { display: grid; gap: 14px; }
.panel { padding: 14px 16px; }
.panel h3 { margin: 0 0 10px; font-size: 14px; }
.hint { font-size: 12px; color: var(--text-muted); font-weight: normal; }
</style>
