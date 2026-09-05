<template>
  <div class="workflow">
    <el-alert v-if="workflowError" type="error" title="机会更新失败，请检查状态、证据、原因或权限后重试。" :closable="false" show-icon />
    <CustomerHubWorkspace ref="workspace" kind="opportunities" @edit-opportunity="open" />
    <el-dialog :close-on-click-modal="!workflowLoading" :close-on-press-escape="!workflowLoading" :show-close="!workflowLoading" v-model="visible" title="更新客户机会" width="min(620px, calc(100vw - 32px))">
      <el-alert v-if="workflowError" type="error" title="保存失败，填写内容已保留。请确认所选记录支持当前机会阶段，或刷新后重试。" :closable="false" show-icon />
      <el-form :disabled="workflowLoading" label-position="top" class="opportunity-form">
        <el-form-item label="目标状态"><el-select v-model="form.status" @change="resetCloseReason"><el-option v-for="status in transitionOptions" :key="status" :label="statusLabel(status)" :value="status" /></el-select></el-form-item>
        <el-form-item label="更新原因（必填）"><el-input v-model="form.reason" type="textarea" :rows="3" /></el-form-item>
        <el-form-item v-if="needsEventEvidence" label="沟通事件证据（必选）"><EvidencePicker v-if="visible" v-model="form.evidenceEventIds" :disabled="workflowLoading" :customer-id="customerId" :opportunity-id="currentId" :target-status="form.status" kind="event" /></el-form-item>
        <el-form-item label="事实依据（可选）"><EvidencePicker v-if="visible" v-model="form.evidenceFactIds" :disabled="workflowLoading" :customer-id="customerId" /></el-form-item>
        <el-form-item v-if="closeReasonOptions.length" label="关闭原因（必填）"><el-select v-model="form.closeReasonCode"><el-option v-for="reason in visibleCloseReasonOptions" :key="reason" :label="reasonLabels[reason] || reason" :value="reason" /></el-select></el-form-item>
        <el-form-item v-if="form.status === 'won' && form.closeReasonCode === 'order_confirmed'" label="有效订单 ID（必填）"><el-input-number v-model="form.linkedOrderId" :min="1" :controls="false" /></el-form-item>
        <el-form-item v-if="closeReasonOptions.length" :label="form.closeReasonCode === 'manual_confirmed' ? '人工确认说明（必填）' : '关闭原因说明'"><el-input v-model="form.closeReasonText" type="textarea" :rows="2" /></el-form-item>
      </el-form>
      <template #footer><GlassButton variant="ghost" :disabled="workflowLoading" @click="visible = false">取消</GlassButton><GlassButton v-any-permission="['customer_opportunity:write','customer:admin']" variant="primary" :loading="workflowLoading" :disabled="!canSubmit || workflowLoading" @click="save">更新</GlassButton></template>
    </el-dialog>
  </div>
</template>
<script setup>
import { computed, reactive, ref } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { msgSuccess } from '@/utils/feedback'
import CustomerHubWorkspace from './CustomerHubWorkspace.vue'
import EvidencePicker from './EvidencePicker.vue'
import { reasonLabels, statusLabel } from './operationsPresentation'
import { useOpportunityWorkflow } from './composables/useCustomerHub'
import { buildOpportunityUpdate, getOpportunityCloseReasonOptions, getOpportunityTransitionOptions } from './customerHubController'
const auth = useAuthStore()
const { workflowLoading, workflowError, submit } = useOpportunityWorkflow()
const visible = ref(false), currentId = ref(null), currentStatus = ref(null), workspace = ref(null), customerId = ref(null)
const form = reactive({ status: '', reason: '', closeReasonCode: '', closeReasonText: '', linkedOrderId: null, evidenceEventIds: [], evidenceFactIds: [] })
const transitionOptions = computed(() => getOpportunityTransitionOptions(currentStatus.value))
const closeReasonOptions = computed(() => getOpportunityCloseReasonOptions(form.status))
const visibleCloseReasonOptions = computed(() => closeReasonOptions.value.filter(reason => reason !== 'manual_confirmed' || auth.hasPermission('customer_opportunity:confirm_without_order')))
const needsEventEvidence = computed(() => ['contacted', 'replied', 'quoted'].includes(form.status))
const hasEventEvidence = computed(() => form.evidenceEventIds.length > 0)
const canSubmit = computed(() => {
  if (!transitionOptions.value.includes(form.status) || !form.reason.trim()) return false
  if (needsEventEvidence.value && !hasEventEvidence.value) return false
  if (closeReasonOptions.value.length && !form.closeReasonCode) return false
  if (form.status === 'won' && form.closeReasonCode === 'order_confirmed' && !form.linkedOrderId) return false
  if (form.closeReasonCode === 'manual_confirmed' && !form.closeReasonText.trim()) return false
  return true
})
function resetCloseReason() { form.closeReasonCode = ''; form.closeReasonText = ''; form.linkedOrderId = null }
function open(row) { if (workflowLoading.value) return; customerId.value = row.customer_id; currentId.value = row.opportunity_id; currentStatus.value = row.status; Object.assign(form, { status: transitionOptions.value[0] || '', reason: '', closeReasonCode: '', closeReasonText: '', linkedOrderId: null, evidenceEventIds: [], evidenceFactIds: [] }); visible.value = true }
async function save() { if (!canSubmit.value || workflowLoading.value) return; if (await submit(currentId.value, buildOpportunityUpdate(form))) { visible.value = false; workspace.value.refresh(); msgSuccess('客户机会已更新') } }
</script>
<style scoped>.workflow { display: grid; gap: 12px; }.opportunity-form :deep(.el-select),.opportunity-form :deep(.el-input-number) { width: 100%; }</style>
