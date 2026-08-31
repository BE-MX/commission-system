<template>
  <div class="workflow">
    <el-alert v-if="workflowError" type="error" title="机会更新失败，请检查状态、证据、原因或权限后重试。" :closable="false" show-icon />
    <CustomerHubWorkspace :key="refreshKey" kind="opportunities" @edit-opportunity="open" />
    <el-dialog v-model="visible" title="更新客户机会" width="620">
      <el-form label-position="top" class="opportunity-form">
        <el-form-item label="目标状态"><el-select v-model="form.status" @change="resetCloseReason"><el-option v-for="status in transitionOptions" :key="status" :label="status" :value="status" /></el-select></el-form-item>
        <el-form-item label="更新原因（必填）"><el-input v-model="form.reason" type="textarea" :rows="3" /></el-form-item>
        <el-form-item v-if="needsEventEvidence" label="证据事件 ID（必填，逗号分隔）" :error="eventEvidenceError"><el-input v-model="form.evidenceEventIdsText" placeholder="例如 1024, 1025" /></el-form-item>
        <el-form-item label="证据事实 ID（可选，逗号分隔）" :error="factEvidenceError"><el-input v-model="form.evidenceFactIdsText" /></el-form-item>
        <el-form-item v-if="closeReasonOptions.length" label="关闭原因（必填）"><el-select v-model="form.closeReasonCode"><el-option v-for="reason in visibleCloseReasonOptions" :key="reason" :label="reason" :value="reason" /></el-select></el-form-item>
        <el-form-item v-if="form.status === 'won' && form.closeReasonCode === 'order_confirmed'" label="有效订单 ID（必填）"><el-input-number v-model="form.linkedOrderId" :min="1" :controls="false" /></el-form-item>
        <el-form-item v-if="closeReasonOptions.length" :label="form.closeReasonCode === 'manual_confirmed' ? '人工确认说明（必填）' : '关闭原因说明'"><el-input v-model="form.closeReasonText" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="visible = false">取消</el-button><el-button v-any-permission="['customer_opportunity:write','customer:admin']" type="primary" :loading="workflowLoading" :disabled="!canSubmit" @click="save">更新</el-button></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { msgSuccess } from '@/utils/feedback'
import CustomerHubWorkspace from './CustomerHubWorkspace.vue'
import { useOpportunityWorkflow } from './composables/useCustomerHub'
import { buildOpportunityUpdate, getInvalidIdTokens, getOpportunityCloseReasonOptions, getOpportunityTransitionOptions } from './customerHubController'
const auth = useAuthStore()
const { workflowLoading, workflowError, submit } = useOpportunityWorkflow()
const visible = ref(false), currentId = ref(null), currentStatus = ref(null), refreshKey = ref(0)
const form = reactive({ status: '', reason: '', closeReasonCode: '', closeReasonText: '', linkedOrderId: null, evidenceEventIdsText: '', evidenceFactIdsText: '' })
const transitionOptions = computed(() => getOpportunityTransitionOptions(currentStatus.value))
const closeReasonOptions = computed(() => getOpportunityCloseReasonOptions(form.status))
const visibleCloseReasonOptions = computed(() => closeReasonOptions.value.filter(reason => reason !== 'manual_confirmed' || auth.hasPermission('customer_opportunity:confirm_without_order')))
const needsEventEvidence = computed(() => ['contacted', 'replied', 'quoted'].includes(form.status))
const hasEventEvidence = computed(() => form.evidenceEventIdsText.split(',').some(item => /^\d+$/.test(item.trim())))
const eventEvidenceError = computed(() => {
  const invalid = getInvalidIdTokens(form.evidenceEventIdsText)
  return invalid.length ? `证据 ID 格式错误：${invalid.join('、')}` : ''
})
const factEvidenceError = computed(() => {
  const invalid = getInvalidIdTokens(form.evidenceFactIdsText)
  return invalid.length ? `证据 ID 格式错误：${invalid.join('、')}` : ''
})
const canSubmit = computed(() => {
  if (!transitionOptions.value.includes(form.status) || !form.reason.trim()) return false
  if (needsEventEvidence.value && !hasEventEvidence.value) return false
  if (eventEvidenceError.value || factEvidenceError.value) return false
  if (closeReasonOptions.value.length && !form.closeReasonCode) return false
  if (form.status === 'won' && form.closeReasonCode === 'order_confirmed' && !form.linkedOrderId) return false
  if (form.closeReasonCode === 'manual_confirmed' && !form.closeReasonText.trim()) return false
  return true
})
function resetCloseReason() { form.closeReasonCode = ''; form.closeReasonText = ''; form.linkedOrderId = null }
function open(row) { currentId.value = row.opportunity_id; currentStatus.value = row.status; Object.assign(form, { status: transitionOptions.value[0] || '', reason: '', closeReasonCode: '', closeReasonText: '', linkedOrderId: null, evidenceEventIdsText: '', evidenceFactIdsText: '' }); visible.value = true }
async function save() { if (await submit(currentId.value, buildOpportunityUpdate(form))) { visible.value = false; refreshKey.value++; msgSuccess('客户机会已更新') } }
</script>
<style scoped>.workflow { display: grid; gap: 12px; }.opportunity-form :deep(.el-select),.opportunity-form :deep(.el-input-number) { width: 100%; }</style>
