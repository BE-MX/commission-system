<template>
  <div class="workflow">
    <div class="actions"><el-button v-permission="'sales_automation:admin'" type="primary" @click="batchDialog = true">创建公海批次</el-button></div>
    <el-alert v-if="workflowError" type="error" title="操作失败，请检查策略版本、配额或权限后重试。" :closable="false" show-icon />
    <CustomerHubWorkspace :key="refreshKey" kind="research" @inspect-task="inspectTask" />
    <el-drawer v-model="detailVisible" title="背调任务详情" size="640px">
      <div v-loading="detailLoading" class="detail-body">
        <el-alert v-if="detailError" type="error" title="任务详情加载失败；列表信息不能替代复核依据。" :closable="false" show-icon><template #default><el-button link type="primary" @click="retryTaskDetail">重试</el-button></template></el-alert>
        <template v-else-if="detail?.content_redacted">
          <el-alert type="warning" title="该任务内容已脱敏，不能作为复核依据。" :closable="false" show-icon />
        </template>
        <template v-else-if="detail">
          <DetailField label="选择原因" :value="detail.selection_reason" /><DetailField label="输入快照" :value="detail.input_snapshot" /><DetailField label="研究结果" :value="detail.result_json" /><DetailField label="研究摘要" :value="detail.research_summary" /><DetailField label="证据事实 ID" :value="detail.evidence_fact_ids" />
          <p class="timestamp">最近更新：{{ formatDate(detail.updated_at) }}</p>
          <div v-if="reviewReady" class="review-actions"><el-button v-permission="'sales_automation:admin'" type="success" :loading="workflowLoading" :disabled="workflowLoading" @click="review('accepted')">通过复核</el-button><el-button v-permission="'sales_automation:admin'" type="warning" :loading="workflowLoading" :disabled="workflowLoading" @click="review('revision_requested')">要求修订</el-button><el-button v-permission="'sales_automation:admin'" type="danger" :loading="workflowLoading" :disabled="workflowLoading" @click="review('rejected')">驳回结果</el-button></div>
          <el-alert v-else type="info" title="仅已完成的背调任务可进行结果复核。" :closable="false" show-icon />
        </template>
      </div>
    </el-drawer>
    <el-dialog v-model="batchDialog" title="创建公海批次" width="520"><el-form label-position="top"><el-form-item label="策略版本"><el-input v-model="batch.policy_version" /></el-form-item><el-form-item label="配额 JSON"><el-input v-model="batch.quotasText" type="textarea" :rows="6" /></el-form-item></el-form><template #footer><el-button @click="batchDialog = false">取消</el-button><el-button type="primary" :loading="workflowLoading" @click="submitBatch">创建</el-button></template></el-dialog>
  </div>
</template>
<script setup>
import { computed, defineComponent, h, reactive, ref } from 'vue'
import { msgError, msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import CustomerHubWorkspace from './CustomerHubWorkspace.vue'
import { canReviewResearchDetail, getResearchReviewSuccessMessage } from './customerHubController'
import { useResearchWorkflows } from './composables/useCustomerHub'
const { workflowLoading, workflowError, createBatch, reviewTask, detail, detailLoading, detailError, detailTaskId, loadTaskDetail, retryTaskDetail } = useResearchWorkflows()
const refreshKey = ref(0), batchDialog = ref(false), detailVisible = ref(false)
const reviewReady = computed(() => canReviewResearchDetail({ loading: detailLoading.value, error: detailError.value, data: detail.value }, detailTaskId.value))
const batch = reactive({ policy_version: '', quotasText: '{}' })
const formatDate = value => value ? formatBeijingDateTime(value) : '未提供'
async function inspectTask(row) { detailVisible.value = true; await loadTaskDetail(row.research_task_id) }
async function submitBatch() { let quotas; try { quotas = JSON.parse(batch.quotasText) } catch { msgError('配额 JSON 格式错误'); return } if (await createBatch({ policy_version: batch.policy_version, quotas_json: quotas, profile_conditions: {} })) { batchDialog.value = false; refreshKey.value++; msgSuccess('创建公海批次') } }
async function review(status) { if (!reviewReady.value || workflowLoading.value) return; if (await reviewTask(detailTaskId.value, status)) { detailVisible.value = false; refreshKey.value++; msgSuccess(getResearchReviewSuccessMessage(status)) } }
const DetailField = defineComponent({ props: { label: String, value: null }, setup(props) { return () => h('section', { class: 'detail-field' }, [h('h3', props.label), h('pre', props.value == null || (Array.isArray(props.value) && !props.value.length) ? '该任务未提供' : typeof props.value === 'string' ? props.value : JSON.stringify(props.value, null, 2))]) } })
</script>
<style scoped>
.workflow { display: grid; gap: 12px; }.actions,.review-actions { display: flex; justify-content: flex-end; gap: 8px; }.detail-body { min-height: 160px; }.detail-field { margin-bottom: 12px; padding: 12px; border: 1px solid var(--border-color); border-radius: 8px; }.detail-field h3 { margin: 0 0 8px; font-size: 14px; }.detail-field pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-secondary); font: inherit; line-height: 1.6; }.timestamp { color: var(--text-secondary); font-size: 13px; }
</style>
