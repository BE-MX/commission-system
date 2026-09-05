<template>
  <div class="workflow">
    <div class="actions"><GlassButton v-permission="'sales_automation:admin'" variant="primary" left-icon="Plus" @click="batchDialog = true">公海筛选规则与批次</GlassButton></div>
    <el-alert v-if="workflowError" type="error" title="操作失败，请检查策略版本、配额或权限后重试。" :closable="false" show-icon />
    <el-tabs v-model="activeTab">
      <el-tab-pane label="研究任务与质量审核" name="research"><CustomerHubWorkspace ref="workspace" kind="research" @inspect-task="inspectTask" /></el-tab-pane>
      <el-tab-pane label="开发资格待审" name="qualification" lazy><QualificationPanel ref="qualification" /></el-tab-pane>
    </el-tabs>
    <el-drawer v-model="detailVisible" title="背调任务详情" size="min(640px, 100vw)">
      <div v-loading="detailLoading" class="detail-body">
        <el-alert v-if="detailError" type="error" title="任务详情加载失败；列表信息不能替代复核依据。" :closable="false" show-icon><template #default><el-button link type="primary" @click="retryTaskDetail">重试</el-button></template></el-alert>
        <template v-else-if="detail?.content_redacted">
          <el-alert type="warning" title="该任务内容已脱敏，不能作为复核依据。" :closable="false" show-icon />
        </template>
        <template v-else-if="detail">
          <ResearchSummary :detail="detail" />
          <p class="timestamp">最近更新：{{ formatDate(detail.updated_at) }}</p>
          <div v-if="reviewReady" class="review-actions"><GlassButton v-permission="'sales_automation:admin'" variant="success" left-icon="Check" :loading="workflowLoading" :disabled="workflowLoading" @click="review('accepted')">通过复核</GlassButton><GlassButton v-permission="'sales_automation:admin'" variant="warning" left-icon="RefreshLeft" :loading="workflowLoading" :disabled="workflowLoading" @click="review('revision_requested')">要求修订</GlassButton><GlassButton v-permission="'sales_automation:admin'" variant="danger" left-icon="Close" :loading="workflowLoading" :disabled="workflowLoading" @click="review('rejected')">驳回结果</GlassButton></div>
          <el-alert v-else type="info" title="仅已完成的背调任务可进行结果复核。" :closable="false" show-icon />
        </template>
      </div>
    </el-drawer>
    <PublicPoolRules v-model="batchDialog" @created="workspace?.refresh()" />
  </div>
</template>
<script setup>
import { computed, ref } from 'vue'
import { msgSuccess } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import CustomerHubWorkspace from './CustomerHubWorkspace.vue'
import ResearchSummary from './ResearchSummary.vue'
import QualificationPanel from './QualificationPanel.vue'
import PublicPoolRules from './PublicPoolRules.vue'
import { canReviewResearchDetail, getResearchReviewSuccessMessage } from './customerHubController'
import { useResearchWorkflows } from './composables/useCustomerHub'
const { workflowLoading, workflowError, reviewTask, detail, detailLoading, detailError, detailTaskId, loadTaskDetail, retryTaskDetail } = useResearchWorkflows()
const workspace = ref(null), qualification = ref(null), activeTab = ref('research'), batchDialog = ref(false), detailVisible = ref(false)
const reviewReady = computed(() => canReviewResearchDetail({ loading: detailLoading.value, error: detailError.value, data: detail.value }, detailTaskId.value))
const formatDate = value => value ? formatBeijingDateTime(value) : '未提供'
async function inspectTask(row) { detailVisible.value = true; await loadTaskDetail(row.research_task_id) }
async function review(status) { if (!reviewReady.value || workflowLoading.value) return; if (await reviewTask(detailTaskId.value, status)) { detailVisible.value = false; workspace.value.refresh(); qualification.value?.refresh(); msgSuccess(getResearchReviewSuccessMessage(status)) } }
</script>
<style scoped>
.workflow { display: grid; gap: 12px; }.actions,.review-actions { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; }.detail-body { min-height: 160px; }.detail-field { margin-bottom: 12px; padding: 12px; border: 1px solid var(--border-color); border-radius: 8px; }.detail-field h3 { margin: 0 0 8px; font-size: 14px; }.detail-field pre { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-secondary); font: inherit; line-height: 1.6; }.timestamp { color: var(--text-secondary); font-size: 13px; }
</style>
