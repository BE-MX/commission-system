<template>
  <div v-loading="loading" class="workspace-page">
    <header class="workspace-header">
      <div class="header-left">
        <GlassButton variant="ghost" left-icon="ArrowLeft" @click="$router.push('/aftersales/cases')">返回</GlassButton>
        <div>
          <div class="title-line"><h1>{{ isNew ? '新建售后单' : caseData.case_no }}</h1><el-tag :type="statusType" effect="plain">{{ STATUS_LABELS[caseData.current_status] || caseData.current_status }}</el-tag></div>
          <p>{{ isNew ? '先登记事实和证据，再让 AI 基于 SOP 生成建议' : `${caseData.customer_name_snapshot || '—'} · ${caseData.order_no_snapshot || '—'}` }}</p>
        </div>
      </div>
      <div v-if="!isNew" class="header-actions">
        <GlassButton v-if="['awaiting_supervisor', 'awaiting_director'].includes(caseData.current_status)" v-permission="'aftersales:admin'" variant="secondary" left-icon="Switch" @click="openTransfer">转交审批</GlassButton>
        <GlassButton variant="secondary" left-icon="Clock" @click="timelineVisible = true">审计记录</GlassButton>
      </div>
    </header>

    <div v-if="!isNew" class="progress-strip">
      <div v-for="step in progressSteps" :key="step.code" class="progress-item" :class="step.state"><span></span><strong>{{ step.label }}</strong></div>
    </div>

    <main class="workspace-grid">
      <div class="registration-column">
        <CaseRegistration
          :form="form" :locked="locked" :options="options" :customers="customers" :orders="orders" :products="products"
          @search-customer="searchCustomers" @customer-change="customerChanged" @search-order="searchOrders" @order-change="orderChanged"
          @search-product="searchProducts" @product-change="productChanged" @product-mode-change="productModeChanged"
        />
        <EvidencePanel
          v-if="!isNew" :case-data="caseData" v-model:files="evidenceFiles" :locked="locked" :can-request-waiver="canRequestWaiver" :upload-fn="uploadEvidence"
          @remove="removeEvidence" @download="downloadEvidence" @request-waiver="requestEvidenceWaiver"
          @update:sales-confirmed="value => { form.sales_evidence_confirmed = value; caseData.sales_evidence_confirmed = value }"
          @update:sales-note="value => { form.sales_evidence_note = value; caseData.sales_evidence_note = value }"
        />
        <div v-else class="evidence-placeholder"><el-icon><Upload /></el-icon><div><strong>保存草稿后上传证据</strong><span>客户和订单确定后，系统会建立安全的私有附件空间。</span></div></div>
      </div>

      <div class="decision-column">
        <AiDecisionPanel
          :case-data="caseData" :latest-ai="latestAi" :options="options" :locked="locked" :analyzing="analyzing"
          v-model:actions="actions" v-model:reply-draft="replyDraft" v-model:responsibility-class="responsibilityClass"
          v-model:responsibility-reason="responsibilityReason" v-model:override-reason="overrideReason"
          @analyze="analyze" @copy-reply="copyReply"
        />
        <ApprovalRoute v-if="!isNew" :case-data="caseData" />
        <section v-if="caseData.execution_result" class="execution-card"><div class="section-title"><el-icon><CircleCheck /></el-icon>执行结果</div><p>{{ caseData.execution_result }}</p><span v-if="caseData.customer_feedback">客户反馈：{{ caseData.customer_feedback }}</span></section>
      </div>
    </main>

    <ReviewActions v-if="canReviewWaiver" class="sticky-actions" waiver @review="reviewEvidenceWaiver" />
    <ReviewActions v-else-if="canReview" class="sticky-actions" @review="review" />
    <footer v-else class="sticky-actions standard-actions">
      <div class="action-hint">{{ actionHint }}</div>
      <div class="action-buttons">
        <GlassButton v-if="canWithdraw" variant="secondary" left-icon="RefreshLeft" @click="withdraw">撤回审核</GlassButton>
        <GlassButton v-if="canReopen" v-permission="'aftersales:admin'" variant="secondary" left-icon="RefreshLeft" @click="reopen">重新打开</GlassButton>
        <GlassButton v-if="canExecute" variant="secondary" left-icon="Finished" @click="execute">登记执行结果</GlassButton>
        <GlassButton v-if="canClose" variant="primary" left-icon="CircleCheck" @click="close">确认客户结果并关闭</GlassButton>
        <GlassButton v-else-if="editableDecision" variant="secondary" left-icon="DocumentChecked" :loading="saving" @click="saveDecision()">保存措施</GlassButton>
        <GlassButton v-if="isNew || editableRegistration" variant="secondary" left-icon="Document" :loading="saving" @click="saveDraft()">保存草稿</GlassButton>
        <GlassButton v-if="canSubmit" variant="primary" left-icon="Promotion" :loading="saving" @click="submit">提交直属主管</GlassButton>
      </div>
    </footer>

    <el-drawer v-model="timelineVisible" title="审计记录" size="520px">
      <el-timeline>
        <el-timeline-item v-for="item in timeline.events" :key="item.id" :timestamp="formatTime(item.created_at)" placement="top">
          <strong>{{ eventLabel(item.event_type) }}</strong><p>{{ item.actor_name || '系统' }}<span v-if="item.detail?.comment">：{{ item.detail.comment }}</span></p>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!timeline.events?.length" description="暂无审计事件" />
      <el-divider content-position="left">钉钉通知</el-divider>
      <div v-for="item in timeline.notifications || []" :key="item.id" class="notification-row">
        <div><strong>{{ notificationLabel(item.template_code) }}</strong><span>尝试 {{ item.attempt_count }} 次 · {{ formatTime(item.sent_at || item.created_at) }}</span><small v-if="item.last_error_summary">{{ item.last_error_summary }}</small></div>
        <el-tag :type="item.status === 'success' ? 'success' : item.status === 'failed' ? 'danger' : 'warning'" effect="plain">{{ item.status === 'success' ? '已发送' : item.status === 'failed' ? '待重试' : '待发送' }}</el-tag>
        <GlassButton v-if="item.status === 'failed'" v-permission="'aftersales:admin'" variant="link" left-icon="Refresh" @click="retryNotification(item.id)">手动重试</GlassButton>
      </div>
      <el-empty v-if="!timeline.notifications?.length" description="暂无通知记录" />
    </el-drawer>

    <el-dialog v-model="transferVisible" title="转交当前审批" width="520px">
      <el-form label-position="top">
        <el-form-item label="新审批人" required>
          <el-select v-model="selectedReviewerId" filterable remote :remote-method="searchReviewers" placeholder="输入姓名或账号搜索">
            <el-option v-for="item in reviewers" :key="item.user_id" :label="`${item.real_name}（${item.username}）`" :value="item.user_id" />
          </el-select>
        </el-form-item>
        <el-form-item label="转交原因" required><el-input v-model="transferReason" type="textarea" :rows="3" maxlength="2000" show-word-limit /></el-form-item>
      </el-form>
      <template #footer><GlassButton variant="secondary" @click="transferVisible = false">取消</GlassButton><GlassButton variant="primary" left-icon="Switch" @click="submitTransfer">确认转交</GlassButton></template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import CaseRegistration from './components/CaseRegistration.vue'
import EvidencePanel from './components/EvidencePanel.vue'
import AiDecisionPanel from './components/AiDecisionPanel.vue'
import ApprovalRoute from './components/ApprovalRoute.vue'
import ReviewActions from './components/ReviewActions.vue'
import { useAfterSalesWorkspace } from './composables/useAfterSalesWorkspace'
import { approvalSteps, STATUS_LABELS } from './aftersalesRules'

const timelineVisible = ref(false)
const transferVisible = ref(false)
const selectedReviewerId = ref(null)
const transferReason = ref('')
const workspace = useAfterSalesWorkspace()
const {
  loading, saving, analyzing, options, caseData, form, timeline, evidenceFiles, customers, orders, products, reviewers, actions,
  replyDraft, responsibilityClass, responsibilityReason, overrideReason, isNew, locked, latestAi, canReview, canReviewWaiver, currentUserId,
  initialize, saveDraft, searchCustomers, customerChanged, searchOrders, orderChanged, searchProducts, productChanged,
  productModeChanged, searchReviewers, uploadEvidence, removeEvidence, downloadEvidence, analyze, saveDecision, submit, review,
  requestEvidenceWaiver, reviewEvidenceWaiver, transferApproval, retryNotification, withdraw, execute, close, reopen, copyReply,
} = workspace
const progressSteps = computed(() => approvalSteps(caseData))
const editableRegistration = computed(() => ['draft', 'ai_failed', 'awaiting_sales_decision', 'returned'].includes(caseData.current_status))
const editableDecision = computed(() => ['ai_failed', 'awaiting_sales_decision', 'returned'].includes(caseData.current_status))
const canSubmit = computed(() => editableDecision.value && actions.value.length > 0 && form.sales_evidence_confirmed !== null && (caseData.evidence_is_sufficient || caseData.evidence_waiver_approved))
const canRequestWaiver = computed(() => editableRegistration.value && !caseData.evidence_is_sufficient && !caseData.evidence_waiver_approved && Number(caseData.creator_user_id) === Number(currentUserId.value))
const canWithdraw = computed(() => caseData.current_status === 'awaiting_supervisor' && Number(caseData.creator_user_id) === Number(currentUserId.value))
const canReopen = computed(() => ['closed', 'rejected'].includes(caseData.current_status))
const isCreator = computed(() => Number(caseData.creator_user_id) === Number(currentUserId.value))
const canExecute = computed(() => caseData.current_status === 'approved' && isCreator.value)
const canClose = computed(() => caseData.current_status === 'processing' && isCreator.value)
const statusType = computed(() => ['approved', 'closed'].includes(caseData.current_status) ? 'success' : ['rejected', 'ai_failed'].includes(caseData.current_status) ? 'danger' : ['returned', 'awaiting_evidence_waiver', 'awaiting_supervisor', 'awaiting_director'].includes(caseData.current_status) ? 'warning' : 'info')
const actionHint = computed(() => ({
  draft: '保存草稿后即可上传证据并生成 AI 建议', ai_analyzing: 'AI 正在后台分析，可离开页面后返回',
  awaiting_sales_decision: '确认责任、措施和英文话术后提交主管', returned: '按审批意见补充后可再次提交',
  awaiting_evidence_waiver: '等待直属主管确认是否允许在现有证据基础上继续',
  awaiting_supervisor: '等待直属主管审核，未处理前可以撤回', awaiting_director: '主管已通过，等待销售总监终审',
  approved: '方案已批准，请登记实际执行结果', processing: '记录客户最终反馈后关闭', closed: '售后单已关闭并进入复盘数据',
})[caseData.current_status] || '查看当前流程状态')
function formatTime(value) { return value ? new Date(value).toLocaleString('zh-CN', { hour12: false }) : '' }
function eventLabel(type) { return ({ created: '创建售后单', updated: '更新登记信息', decision_saved: '保存处理措施', evidence_waiver_requested: '申请证据豁免', evidence_waiver_approve: '证据豁免通过', evidence_waiver_reject: '证据豁免拒绝', submitted: '提交审核', review_proxied: '管理员代理审核', review_approve: '审核通过', review_return: '退回补充', review_reject: '拒绝方案', approval_transferred: '审批转交', withdrawn: '撤回审核', execution_updated: '登记执行结果', closed: '关闭售后单', reopened: '重新打开' })[type] || type }
function notificationLabel(type) { return ({ awaiting_supervisor: '主管待审通知', awaiting_director: '总监待审通知', approved: '最终通过通知', returned: '退回通知', rejected: '拒绝通知', approval_transferred: '审批转交通知', evidence_waiver_requested: '证据豁免待确认', evidence_waiver_approve: '证据豁免通过', evidence_waiver_reject: '证据豁免拒绝' })[type] || type }
async function openTransfer() { selectedReviewerId.value = null; transferReason.value = ''; transferVisible.value = true; await searchReviewers('') }
async function submitTransfer() {
  if (!selectedReviewerId.value || !transferReason.value.trim()) return
  await transferApproval(selectedReviewerId.value, transferReason.value.trim())
  transferVisible.value = false
}
onMounted(initialize)
</script>

<style scoped>
.header-actions { display: flex; align-items: center; gap: 8px; }
.notification-row { display: grid; grid-template-columns: minmax(0, 1fr) auto auto; gap: 10px; align-items: center; padding: 10px 0; border-bottom: 1px solid var(--border-color); }.notification-row > div { display: flex; flex-direction: column; gap: 2px; }.notification-row span, .notification-row small { color: var(--text-secondary); font-size: 11px; }.notification-row small { color: var(--color-danger-text); }
.workspace-page { min-width: 0; padding-bottom: 96px; }.workspace-header, .header-left, .title-line, .action-buttons { display: flex; align-items: center; }.workspace-header { justify-content: space-between; gap: 16px; margin-bottom: 16px; }.header-left { gap: 10px; }.title-line { gap: 10px; }.title-line h1 { margin: 0; color: var(--text-primary); font: 700 20px/1.3 var(--font-display); }.header-left p { margin: 3px 0 0; color: var(--text-secondary); font-size: 12px; }.progress-strip { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 4px; padding: 12px 16px; margin-bottom: 16px; border: 1px solid var(--border-color); border-radius: var(--card-radius); background: var(--card-bg); }.progress-item { display: flex; align-items: center; gap: 7px; min-width: 0; color: var(--text-muted); }.progress-item span { width: 8px; height: 8px; flex: 0 0 auto; border-radius: 50%; background: var(--border-hover); }.progress-item strong { overflow: hidden; font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }.progress-item.done span { background: var(--color-success); }.progress-item.active span { background: var(--color-primary); box-shadow: 0 0 0 4px var(--color-primary-light); }.progress-item.active strong { color: var(--text-primary); }.workspace-grid { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(360px, .85fr); gap: 16px; align-items: start; }.registration-column, .decision-column { display: grid; gap: 16px; }.evidence-placeholder, .execution-card { display: flex; gap: 12px; padding: 18px; border: 1px dashed var(--border-hover); border-radius: var(--card-radius); background: var(--toolbar-bg); color: var(--text-secondary); }.evidence-placeholder div { display: flex; flex-direction: column; gap: 4px; }.evidence-placeholder span, .execution-card span { font-size: 12px; }.execution-card { display: block; border-style: solid; background: var(--card-bg); }.execution-card .section-title { color: var(--text-primary); font-weight: 700; }.execution-card p { color: var(--text-secondary); line-height: 1.6; }.sticky-actions { position: fixed; z-index: 10; right: 28px; bottom: 18px; left: 268px; }.standard-actions { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 12px 16px; border: 1px solid var(--border-color); border-radius: 14px; background: var(--card-bg); box-shadow: var(--card-shadow-hover); }.action-hint { color: var(--text-secondary); font-size: 12px; }.action-buttons { justify-content: flex-end; gap: 8px; flex-wrap: wrap; } :deep(.el-timeline-item__content p) { color: var(--text-secondary); font-size: 12px; }
@media (max-width: 1100px) { .workspace-grid { grid-template-columns: 1fr; }.sticky-actions { left: 96px; }.progress-strip { overflow-x: auto; grid-template-columns: repeat(6, minmax(120px, 1fr)); } }
@media (max-width: 760px) { .workspace-header, .standard-actions { align-items: stretch; flex-direction: column; }.sticky-actions { right: 12px; bottom: 12px; left: 12px; }.action-buttons { justify-content: stretch; }.action-buttons :deep(button) { flex: 1; } }
</style>
