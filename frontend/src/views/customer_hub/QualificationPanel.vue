<template>
  <section class="qualification-panel">
    <el-alert type="info" title="开发资格决定是否值得继续开发；研究质量审核只确认材料是否可用。审核通过不会改变客户归属。" :closable="false" />
    <div class="toolbar"><el-input v-model="searchForm.keyword" placeholder="搜索待审核客户" clearable @keyup.enter="handleSearch" @clear="handleSearch" /><GlassButton variant="secondary" left-icon="Refresh" :loading="loading" @click="handleSearch">刷新</GlassButton></div>
    <el-alert v-if="error" type="error" title="资格队列加载失败，请重试。" :closable="false" />
    <div v-else class="table-card"><el-table v-loading="loading" :data="list" border class="list-table" row-key="research_task_id">
      <el-table-column prop="customer_name" label="客户" min-width="180" show-overflow-tooltip />
      <el-table-column prop="scope_label" label="开发方向" min-width="160" show-overflow-tooltip />
      <el-table-column label="目标匹配分" min-width="120"><template #default="{ row }">{{ row.match_score ?? '未评估' }}</template></el-table-column>
      <el-table-column label="研究更新" min-width="170"><template #default="{ row }">{{ formatBeijingDateTime(row.updated_at, { seconds: false }) }}</template></el-table-column>
      <el-table-column label="操作" min-width="150" max-width="180" fixed="right"><template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="inspect(row)">{{ row.can_review ? '审阅并决定' : '查看受限原因' }}</GlassButton></template></el-table-column>
      <template #empty>当前没有待做资格判断的客户；已决定或未到重评时间的客户不会重复出现。</template>
    </el-table></div>
    <el-pagination v-model:current-page="page" :page-size="pageSize" :total="total" layout="total, prev, pager, next" @current-change="handlePageChange" />
    <el-drawer class="customer-hub-drawer" v-model="visible" title="开发资格审核" size="min(760px, 100vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
      <div v-loading="context.loading" class="review-body">
        <el-alert v-if="context.error" type="error" title="审核依据加载失败，请重新加载后再决定。" :closable="false"><el-button link @click="reload">重新加载</el-button></el-alert>
        <template v-else-if="context.data">
          <h2>{{ context.data.customer_name }}</h2><p>开发方向：{{ context.data.scope_label || '当前可见范围' }} · 目标匹配分：{{ context.data.match_score ?? '未评估' }}</p>
          <p v-if="context.data.previous_reason">上次结论原因：{{ context.data.previous_reason }}</p>
          <ResearchSummary :detail="context.data" />
          <el-alert v-if="!context.data.can_review" type="warning" :title="context.data.blocked_reason" :closable="false" />
          <el-form v-else label-position="top" :disabled="saving" class="decision-form">
            <el-form-item label="开发决定"><el-radio-group v-model="form.decision"><el-radio-button value="approve">值得开发</el-radio-button><el-radio-button value="defer">暂缓开发</el-radio-button><el-radio-button value="supplement">补充证据</el-radio-button><el-radio-button value="reject">不适合</el-radio-button></el-radio-group></el-form-item>
            <el-form-item label="判断理由（必填）"><el-input v-model="form.reason" type="textarea" :rows="3" placeholder="结合需求适配、供应商现状或风险，说明判断依据" /></el-form-item>
            <el-form-item v-if="needsDate" label="重新评估时间（北京时间，必填）"><el-date-picker v-model="form.reviewAfter" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" /></el-form-item>
            <p class="hint">来源、目标范围和证据快照由方舟自动记录。</p>
          </el-form>
          <el-alert v-if="saveError" type="error" title="提交失败，内容已保留。如研究或已有结论发生变化，请重新加载依据后再决定。" :closable="false"><el-button link :disabled="saving" @click="reload">重新加载依据</el-button></el-alert>
        </template>
      </div>
      <template #footer><GlassButton variant="ghost" :disabled="saving" @click="visible = false">关闭</GlassButton><GlassButton v-any-permission="['sales_automation:write','sales_automation:admin']" variant="primary" :loading="saving" :disabled="!canSubmit || saving" @click="save">提交决定</GlassButton></template>
    </el-drawer>
  </section>
</template>
<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { listQualificationQueue, getQualificationContext, submitQualificationDecision } from '@/api/customerHub'
import { formatBeijingDateTime, parseApiDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { createLatestResource } from './customerHubResources'
import { createSearchJobIdempotencyKey } from './customerHubController'
import { useOperationsList } from './composables/useOperationsList'
import ResearchSummary from './ResearchSummary.vue'
const visible = ref(false), saving = ref(false), saveError = ref(null), taskId = ref(null), requestKey = ref('')
const context = reactive(createLatestResource(getQualificationContext))
const form = reactive({ decision: 'approve', reason: '', reviewAfter: '' })
const { loading, list, total, page, pageSize, searchForm, error, fetchList, handleSearch, handlePageChange } = useOperationsList(listQualificationQueue, { searchForm: { keyword: '' } })
const needsDate = computed(() => ['defer', 'supplement'].includes(form.decision))
const canSubmit = computed(() => !context.loading && !context.error && context.data?.can_review && context.data?.research_task_id === taskId.value && form.reason.trim() && (!needsDate.value || (parseApiDateTime(form.reviewAfter)?.getTime() || 0) > Date.now()))
watch(form, () => { requestKey.value = createSearchJobIdempotencyKey() }, { flush: 'sync' })
async function reload() { if (saving.value) return; saveError.value = null; requestKey.value = createSearchJobIdempotencyKey(); await context.load(taskId.value) }
async function inspect(row) { if (saving.value) return; taskId.value = row.research_task_id; Object.assign(form, { decision: 'approve', reason: '', reviewAfter: '' }); visible.value = true; await reload() }
async function save() {
  if (!canSubmit.value || saving.value) return
  saving.value = true; saveError.value = null
  try {
    await submitQualificationDecision(taskId.value, { decision: form.decision, reason: form.reason.trim(), review_after: needsDate.value ? `${form.reviewAfter}+08:00` : null, context_hash: context.data.context_hash, expected_current_review_id: context.data.current_review_id, request_key: requestKey.value })
    visible.value = false; msgSuccess('开发资格决定已记录'); await fetchList()
  } catch (error) { saveError.value = error }
  finally { saving.value = false }
}
defineExpose({ refresh: fetchList })
</script>
<style scoped>.qualification-panel { display: grid; gap: 14px; }.toolbar { display: flex; gap: 10px; }.toolbar :deep(.el-input) { max-width: 400px; }.review-body { min-height: 160px; }.review-body h2 { margin: 0; font-size: 17px; }.review-body p { color: var(--text-secondary); line-height: 1.6; }.decision-form { margin-top: 20px; }.decision-form :deep(.el-date-editor) { width: 100%; }.hint { color: var(--text-muted); font-size: 12px; }.el-pagination { overflow-x: auto; }</style>
