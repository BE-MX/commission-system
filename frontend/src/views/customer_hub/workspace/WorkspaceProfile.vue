<template>
  <div class="workspace-profile">
    <section class="lg-card panel">
      <h3>普通字段修订 <span class="hint">治理字段（身份/归属/DNC/风险）走变更提案</span></h3>
      <el-form label-position="top" size="small" @submit.prevent>
        <el-form-item label="字段">
          <el-select v-model="form.field_key" placeholder="选择字段" class="profile-select">
            <el-option v-for="key in PROFILE_FIELD_WHITELIST" :key="key" :value="key" :label="PROFILE_FIELD_LABELS[key]" />
          </el-select>
        </el-form-item>
        <el-form-item label="新值">
          <el-input v-model="form.value" placeholder="依据客户确认填写" class="profile-input" />
        </el-form-item>
        <el-form-item label="依据">
          <el-input v-model="form.reason" type="textarea" :rows="2" placeholder="为什么这样修改" class="profile-input" />
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
              <GlassButton link-tone="success" left-icon="Check" v-permission="'customer_profile:write'" variant="link" @click="decide(row, 'accept')">采纳</GlassButton>
              <GlassButton left-icon="Edit" v-permission="'customer_profile:write'" variant="link" @click="decide(row, 'edit_accept')">编辑采纳</GlassButton>
              <GlassButton link-tone="danger" left-icon="Close" v-permission="'customer_profile:write'" variant="link" @click="decide(row, 'reject')">驳回</GlassButton>
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
        <el-table-column label="时间（北京时间）" min-width="170"><template #default="{row}">{{ row.created_at ? formatBeijingDateTime(row.created_at) : '未提供' }}</template></el-table-column>
      </el-table>
    </section>

    <section class="lg-card panel">
      <h3>客户服务入口 <span class="hint">登记用途与入口；使用表现仅在有可靠来源后展示</span></h3>
      <el-form label-position="top" size="small" @submit.prevent>
        <el-form-item label="类型">
          <el-select v-model="assetForm.asset_type" class="profile-select">
            <el-option value="customer_website" label="客户网站" />
            <el-option value="selection_page" label="选品页" />
            <el-option value="purchase_entry" label="采购入口" />
            <el-option value="material_service" label="素材服务" />
            <el-option value="other" label="其他入口" />
          </el-select>
        </el-form-item>
        <el-form-item label="入口地址"><el-input v-model="assetForm.entry_url" placeholder="https://" class="asset-input" /></el-form-item>
        <el-form-item label="服务用途"><el-input v-model="assetForm.purpose" placeholder="这个入口帮助客户完成什么" class="asset-input" /></el-form-item>
        <el-form-item label="已知问题"><el-input v-model="assetForm.known_issue" placeholder="可选，记录当前障碍" class="asset-input" /></el-form-item>
        <el-form-item><el-button type="primary" :loading="assetSaving" v-permission="'customer_pcw:write'" @click="submitAsset">登记入口</el-button></el-form-item>
      </el-form>
      <el-empty v-if="!assets.length" description="暂无已登记服务入口" :image-size="60" />
      <div v-for="asset in assets" :key="asset.asset_id" class="asset-row">
        <div><strong>{{ asset.purpose }}</strong> · {{ asset.asset_type }}</div>
        <a v-if="/^https?:\/\//i.test(asset.entry_url || '')" :href="asset.entry_url" target="_blank" rel="noopener noreferrer">{{ asset.entry_url }}</a>
        <div v-if="asset.known_issue" class="hint">待处理：{{ asset.known_issue }}</div>
        <template v-if="revokeAssetId === asset.asset_id">
          <el-input v-model="revokeReason" placeholder="撤销原因" class="revoke-input" />
          <el-button type="danger" :loading="assetSaving" @click="confirmRevoke(asset)">确认撤销</el-button>
          <el-button @click="revokeAssetId = null">取消</el-button>
        </template>
        <el-button v-else v-permission="'customer_pcw:write'" @click="revokeAssetId = asset.asset_id">撤销登记</el-button>
      </div>
    </section>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import {
  createProfileRevision, decideProfileSuggestion,
  listProfileRevisions, listProfileSuggestions,
  getCustomer, listCustomerServiceAssets, registerCustomerServiceAsset, revokeCustomerServiceAsset,
} from '@/api/customerHub'
import { msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { createSubmissionIdentity, errorMessage } from '../workbenchV2Controller'
import {
  PROFILE_FIELD_LABELS, PROFILE_FIELD_WHITELIST,
  buildProfileRevisionPayload, buildSuggestionDecisionPayload, isVersionConflict,
} from '../customerWorkspaceController'

const props = defineProps({ customerId: { type: Number, required: true }, customer: { type: Object, default: null } })
const emit = defineEmits(['updated'])
const form = reactive({ field_key: '', value: '', reason: '' })
const suggestions = ref([])
const revisions = ref([])
const saving = ref(false)
const conflictInfo = ref('')
const identity = createSubmissionIdentity('profile')
const suggestionIdentity = createSubmissionIdentity('suggestion')
const assetIdentity = createSubmissionIdentity('service-asset')
const assetRevokeIdentity = createSubmissionIdentity('service-asset-revoke')
const assets = ref([])
const assetForm = reactive({ asset_type: 'customer_website', entry_url: '', purpose: '', known_issue: '' })
const assetSaving = ref(false)
const revokeAssetId = ref(null)
const revokeReason = ref('')
const currentProfile = ref(props.customer)
const profileVersions = () => ({ expected_profile_version_id: currentProfile.value?.current_profile_version_id ?? currentProfile.value?.profile_metadata?.profile_version_id, expected_profile_input_seq: currentProfile.value?.profile_input_seq })

async function loadAll() {
  conflictInfo.value = ''
  try {
    const [suggestionRes, revisionRes, profileRes, assetRes] = await Promise.all([
      listProfileSuggestions(props.customerId, {}),
      listProfileRevisions(props.customerId, {}),
      getCustomer(props.customerId),
      listCustomerServiceAssets(props.customerId),
    ])
    suggestions.value = suggestionRes.data?.items ?? []
    revisions.value = revisionRes.data?.items ?? []
    currentProfile.value = profileRes.data
    assets.value = assetRes.data?.items ?? []
  } catch (error) { conflictInfo.value = errorMessage(error) }
}

async function submitAsset() {
  if (!assetForm.entry_url.trim() || !assetForm.purpose.trim()) {
    conflictInfo.value = '请填写入口地址和服务用途'
    return
  }
  assetSaving.value = true
  conflictInfo.value = ''
  try {
    const payload = { asset_type: assetForm.asset_type, entry_url: assetForm.entry_url.trim(),
      purpose: assetForm.purpose.trim(), known_issue: assetForm.known_issue.trim() || null }
    await registerCustomerServiceAsset(props.customerId, payload, assetIdentity.forPayload(payload))
    assetIdentity.reset()
    msgSuccess('服务入口已登记')
    assetForm.entry_url = ''
    assetForm.purpose = ''
    assetForm.known_issue = ''
    await loadAll()
  } catch (error) { conflictInfo.value = errorMessage(error) }
  finally { assetSaving.value = false }
}

async function confirmRevoke(asset) {
  if (!revokeReason.value.trim()) {
    conflictInfo.value = '请填写撤销原因'
    return
  }
  assetSaving.value = true
  conflictInfo.value = ''
  try {
    const payload = { expected_asset_version: asset.asset_version, reason: revokeReason.value.trim() }
    await revokeCustomerServiceAsset(props.customerId, asset.asset_id, payload,
      assetRevokeIdentity.forPayload({ asset_id: asset.asset_id, ...payload }))
    assetRevokeIdentity.reset()
    msgSuccess('登记已撤销')
    revokeAssetId.value = null
    revokeReason.value = ''
    await loadAll()
  } catch (error) { conflictInfo.value = errorMessage(error) }
  finally { assetSaving.value = false }
}

async function submitRevision() {
  saving.value = true
  conflictInfo.value = ''
  try {
    const payload = buildProfileRevisionPayload(form, profileVersions())
    await createProfileRevision(props.customerId, payload, identity.forPayload(payload))
    msgSuccess('修订已保存并生成新档案版本')
    form.value = ''
    form.reason = ''
    await loadAll()
    emit('updated')
  } catch (error) {
    if (isVersionConflict(error)) {
      conflictInfo.value = '档案已有他人更新，已保留你的输入；请刷新确认后再提交'
    } else conflictInfo.value = errorMessage(error)
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
    ...profileVersions(),
  }
  if (operation === 'reject') {
    const reason = window.prompt('驳回原因（必填）', '')
    if (!reason || !reason.trim()) return
    try {
      const payload = buildSuggestionDecisionPayload(operation, { reason }, versions)
      await decideProfileSuggestion(row.id, payload, suggestionIdentity.forPayload({id:row.id,...payload}))
      msgSuccess('已驳回')
      await loadAll()
    } catch (error) { conflictInfo.value = errorMessage(error) }
    return
  }
  try {
    const payload = buildSuggestionDecisionPayload(operation, { value }, versions)
    await decideProfileSuggestion(row.id, payload, suggestionIdentity.forPayload({id:row.id,...payload}))
    msgSuccess('已采纳')
    await loadAll()
    emit('updated')
  } catch (error) {
    conflictInfo.value = errorMessage(error)
  }
}

onMounted(loadAll)
</script>

<style scoped>
.workspace-profile { display: grid; gap: 14px; }
.panel { padding: 14px 16px; }
.panel h3 { margin: 0 0 10px; font-size: 14px; }
.hint { font-size: 12px; color: var(--text-muted); font-weight: normal; }
.asset-row { display: grid; gap: 5px; padding: 10px 0; border-top: 1px solid var(--border-color); overflow-wrap: anywhere; }
.profile-select { width: min(260px, 100%); }
.profile-input { width: min(320px, 100%); }
.asset-input { width: min(420px, 100%); }
.revoke-input { width: min(360px, 100%); }
</style>
