<template>
  <section class="lg-card enrichment-panel" aria-label="私海客户信息补全">
    <div class="enrichment-intro">
      <strong>客户信息补全</strong>
      <p>核实官网、公司业务、公开联系方式和主营产品。保留已有内容，冲突列出来源，结果回写后供审核。</p>
    </div>
    <div class="enrichment-actions">
      <StatusBadge v-if="task" :type="task.task_status === 'failed' ? 'danger' : 'info'">{{ statusText }}</StatusBadge>
      <GlassButton v-any-permission="['customer_profile:write', 'customer:admin']" variant="primary" left-icon="MagicStick"
        :loading="submitting" :disabled="loading || Boolean(error) || awaitingResult" @click="request">一键补全</GlassButton>
      <GlassButton v-if="task" variant="secondary" left-icon="View" @click="detailVisible = true">查看任务与结果</GlassButton>
      <GlassButton variant="ghost" left-icon="Refresh" :loading="loading" @click="load">刷新状态</GlassButton>
    </div>
    <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
    <DetailDrawer v-model="detailVisible" append-to-body title="客户信息补全" width="760px">
      <template v-if="task">
        <p>任务 #{{ task.research_task_id }} · {{ statusText }}</p>
        <el-alert v-if="task.task_status === 'pending'" title="已入队，等待研究 Agent 领取；刷新状态可查看进展。" type="info" :closable="false" />
        <el-alert v-if="task.task_status === 'failed'" :title="`研究未完成（${task.error_code || '执行失败'}），已有内容已保留，可重新发起。`" type="warning" :closable="false" />
        <ResearchSummary v-if="task.result_json || task.research_summary" :detail="task" />
        <p class="review-note">研究质量通过后仍保留为候选材料；正式档案变更需另行确认。</p>
      </template>
      <template v-if="task?.task_status === 'completed' && task.result_review_status === 'pending'" #footer>
        <GlassButton v-permission="'sales_automation:admin'" variant="success" :loading="reviewing" @click="review('accepted')">通过质量复核</GlassButton>
        <GlassButton v-permission="'sales_automation:admin'" variant="danger" :loading="reviewing" @click="review('rejected')">驳回结果</GlassButton>
      </template>
    </DetailDrawer>
  </section>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { getCustomerEnrichment, requestCustomerEnrichment, reviewResearchTask } from '@/api/customerHub'
import { msgSuccess } from '@/utils/feedback'
import ResearchSummary from '../ResearchSummary.vue'

const props = defineProps({ customerId: { type: Number, required: true } })
const task = ref(null), loading = ref(false), submitting = ref(false), reviewing = ref(false)
const error = ref(''), detailVisible = ref(false)
let timer, disposed = false
const active = computed(() => ['pending', 'running'].includes(task.value?.task_status))
const awaitingResult = computed(() => active.value || (task.value?.task_status === 'completed'
  && ['pending', 'revision_requested'].includes(task.value?.result_review_status)))
const statusText = computed(() => {
  if (task.value?.task_status === 'completed') {
    return { pending: '已完成 · 待审核', accepted: '质量已通过', rejected: '结果已驳回', revision_requested: '待修订' }[task.value.result_review_status] || '已完成'
  }
  return { pending: '等待研究', running: '正在研究', failed: '研究失败', skipped: '已停止研究', cancelled: '已取消' }[task.value?.task_status] || task.value?.task_status
})
function schedule() {
  clearTimeout(timer)
  if (!disposed && active.value && !error.value) timer = setTimeout(load, 15000)
}
async function load() {
  loading.value = true
  error.value = ''
  try { task.value = (await getCustomerEnrichment(props.customerId)).data }
  catch { error.value = '补全任务状态加载失败，请刷新状态后重试。' }
  finally { loading.value = false; schedule() }
}
async function request() {
  if (submitting.value || awaitingResult.value) return
  submitting.value = true
  error.value = ''
  clearTimeout(timer)
  try {
    const { data } = await requestCustomerEnrichment(props.customerId)
    task.value = data.task
    msgSuccess(data.created ? '提交补全任务' : '获取已有补全任务')
    detailVisible.value = true
  } catch (e) { error.value = e?.response?.data?.message || '提交结果未确认，请刷新状态核对后重试。' }
  finally { submitting.value = false; schedule() }
}
async function review(status) {
  if (reviewing.value) return
  reviewing.value = true
  try {
    await reviewResearchTask(task.value.research_task_id, status)
    msgSuccess('研究质量审核')
    await load()
  } catch { error.value = '审核未成功，请刷新任务状态后重试。' }
  finally { reviewing.value = false }
}
onMounted(load)
onUnmounted(() => { disposed = true; clearTimeout(timer) })
</script>

<style scoped>
.enrichment-panel { padding: 16px; display: grid; gap: 12px; }
.enrichment-intro p, .review-note { color: var(--text-secondary); line-height: 1.6; margin: 8px 0 0; }
.enrichment-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
</style>
