<template>
  <section class="decision-panel"><div class="section-heading"><div><h2>今天值得核对的客户</h2><p>同一客户合并展示最多 3 个理由；内部跟进，不向客户自动发送消息</p></div><span class="decision-badge">{{ data.insights.length }} 条事实</span></div><InsightCards :insights="data.insights" :customers="data.customers" :busy="creating" @evidence="$emit('evidence', $event)" @customer="$emit('customer', $event)" @action="prepareAction" /></section>
  <section class="decision-panel"><div class="section-heading"><div><h2>行动闭环</h2><p>结果由负责人记录；备注不自动视为下单、回款或到账事实</p></div><GlassButton :loading="actionsLoading" @click="loadActions">刷新行动</GlassButton></div><el-alert v-if="actionsError" :title="actionsError" type="error" :closable="false" /><div class="action-list"><article v-for="action in actions" :key="action.id" class="action-row"><div class="action-number">{{ action.id }}</div><div class="action-body"><h3>{{ action.title }}</h3><p>{{ customerName(action.customer_id) }} · 到期 {{ action.due_date }} · {{ label(action.status) }}</p><p v-if="action.condition_changed" class="decision-warning">条件已变化：原始证据保留，请核验后关闭或记录结果。</p><p v-if="action.result">实际记录：{{ action.result }}（{{ resultTypes[action.result_type] || '其他' }}）</p><div class="action-bar"><GlassButton variant="link" @click="$emit('customer', action.customer_id)">客户画像</GlassButton><GlassButton v-if="action.evidence?.insight?.evidence_refs?.length" variant="link" @click="$emit('evidence', action.evidence.insight.evidence_refs)">原始证据</GlassButton><GlassButton v-permission="'domestic_decision_action:write'" variant="link" :disabled="action.assignee_user_id !== auth.user?.id || ['done', 'dismissed'].includes(action.status)" @click="editAction(action)">记录进度 / 结果</GlassButton><span v-if="action.assignee_user_id !== auth.user?.id" class="decision-note">仅负责人可更新</span></div></div><el-tag :type="action.status === 'done' ? 'success' : action.condition_changed ? 'warning' : 'info'">{{ label(action.status) }}</el-tag></article><el-empty v-if="!actions.length && !actionsLoading" description="暂无内部行动；先核对事实，再安排跟进" :image-size="64" /></div></section>
  <section class="decision-panel" v-permission="'domestic_decision_report:write'"><div class="section-heading"><div><h2>简报、导出与自然语言查询</h2><p>始终绑定分析快照；AI 解释为待验证假设，事实由程序提供</p></div></div><div class="action-bar"><label class="inline-label">关注点<el-select v-model="focus"><el-option label="经营总览" value="executive" /><el-option label="客户经营" value="customer" /><el-option label="产品需求" value="product" /><el-option v-if="financeAllowed" label="充值与资金" value="finance" /></el-select></label><label class="inline-label">导出格式<el-select v-model="format"><el-option label="CSV" value="csv" /><el-option label="JSON" value="json" /></el-select></label><GlassButton variant="primary" :disabled="!!pendingKind" :loading="pendingKind === 'briefs'" @click="createJob('briefs')">生成事实简报</GlassButton><GlassButton :disabled="!!pendingKind" :loading="pendingKind === 'exports'" @click="createJob('exports')">生成筛选明细导出</GlassButton><GlassButton @click="loadBriefs">历史简报</GlassButton></div><div class="natural-query"><el-input v-model="question" maxlength="500" show-word-limit placeholder="例如：近90天客户复购情况，按工艺和长度看数量" aria-label="自然语言查询问题" @keyup.ctrl.enter="createJob('query-plans')" /><GlassButton :disabled="question.trim().length < 3 || !!pendingKind" :loading="pendingKind === 'query-plans'" @click="createJob('query-plans')">准备查询计划</GlassButton></div><p class="decision-note">先生成可读查询计划，点击应用后才执行查询；Ctrl + Enter 可准备计划。</p><el-alert v-if="jobError" :title="jobError" type="warning" :closable="false" /><GlassButton v-if="jobError && pendingKind" variant="link" @click="acknowledgeUncertain">已核验上次任务，解除待确认状态</GlassButton>
    <div class="job-list"><article v-for="job in jobs" :key="job.id" class="job-card"><header><h3>{{ { brief: '事实简报', export: '明细导出', plan: '查询计划' }[job.kind] || '生成任务' }}</h3><el-tag :type="job.status === 'failed' ? 'danger' : job.status === 'succeeded' ? 'success' : 'info'">{{ label(job.status) }}</el-tag><span class="decision-note">{{ job.source === 'ai' ? 'AI选择注册解释' : job.source === 'snapshot' ? '快照导出' : '规则解析 / 事实' }} · {{ formatBeijingDateTime(job.created_at, { seconds: false }) }}</span></header><p v-if="job.error_message" class="decision-warning">{{ job.error_message }}</p><GlassButton v-if="['queued', 'running'].includes(job.status)" variant="link" @click="refreshJob(job)">检查进度</GlassButton><GlassButton v-if="job.kind === 'export' && job.status === 'succeeded'" variant="link" @click="download(job)">授权下载（完成后24小时）</GlassButton>
      <template v-if="job.kind === 'plan' && job.result"><div class="plan-preview"><strong>待应用计划</strong><p>{{ job.result.explanation }}</p><div class="filter-chips"><span>{{ job.result.query.start_date }} — {{ job.result.query.end_date }}</span><span>{{ METRIC_LABELS[job.result.query.metric] }}</span><span v-for="field in job.result.query.dimensions" :key="field">{{ FIELD_LABELS[field] }}</span><span v-for="(values, field) in job.result.query.filters" :key="field">{{ FIELD_LABELS[field] }}：{{ values.join('、') }}</span></div><p>{{ job.result.notice }}</p><GlassButton variant="primary" @click="$emit('plan', job.result)">核对并应用计划</GlassButton></div></template>
      <template v-if="job.kind === 'brief' && job.result"><h3>{{ job.result.title }}</h3><div class="filter-chips"><span>{{ job.result.meta.period.start_date }} — {{ job.result.meta.period.end_date }}</span><span>{{ job.result.meta.metric_version }}</span><span>规则 {{ job.result.meta.rule_version }}</span><span>{{ job.result.meta.scope_summary.mode === 'all' ? '全部授权范围' : '本人客户范围' }}</span></div><DecisionTable :rows="[job.result.summary]" :columns="briefColumns" :paginate="false" /><div v-for="fact in job.result.facts" :key="fact.fact_id" class="brief-fact"><strong>{{ fact.title }}</strong><p>{{ fact.explanation }}</p><p>下一步：{{ fact.next_step }}</p><GlassButton variant="link" @click="$emit('evidence', fact.evidence_refs)">核验事实 {{ fact.fact_id + 1 }}</GlassButton></div><div v-for="suggestion in job.result.suggestions" :key="suggestion.fact_id" class="brief-hypothesis"><strong>待验证假设</strong><p>{{ suggestion.hypothesis }}</p><p>替代解释：{{ suggestion.alternative_explanation }}</p><p>验证动作：{{ suggestion.next_step }}</p></div><DecisionTable v-if="financeAllowed && job.result.finance" :rows="[job.result.finance]" :columns="briefFinanceColumns" :paginate="false" /><p class="decision-note">{{ job.result.notice }}</p></template>
    </article></div>
  </section>
  <el-dialog v-model="createOpen" title="安排内部行动" width="480px" append-to-body><p>{{ selectedInsight?.title }}</p><p class="decision-note">{{ selectedInsight?.explanation }}</p><p v-if="selectedInsight?.period" class="decision-note">事实周期：{{ selectedInsight.period.start_date }} — {{ selectedInsight.period.end_date }} · {{ selectedInsight.source_run_id ? '已核验的来源快照' : '当前分析快照' }}</p><el-form label-position="top"><el-form-item label="完成期限（北京时间）"><el-date-picker v-model="dueDate" value-format="YYYY-MM-DD" :clearable="false" /></el-form-item></el-form><p class="decision-note">服务端按客户、规则和观察窗口去重；相同信号已关闭时也不会重复创建。</p><template #footer><GlassButton @click="createOpen = false">取消</GlassButton><GlassButton variant="primary" :loading="creating" @click="submitAction">创建行动</GlassButton></template></el-dialog>
  <el-dialog v-model="editOpen" title="记录行动结果" width="640px" append-to-body><el-form label-position="top"><el-form-item label="行动状态"><el-select v-model="edit.status"><el-option v-for="status in ['todo', 'in_progress', 'done', 'dismissed']" :key="status" :value="status" :label="label(status)" /></el-select></el-form-item><el-form-item label="实际结果类型"><el-select v-model="edit.result_type" clearable><el-option v-for="(text, value) in resultTypes" :key="value" :value="value" :label="text" /></el-select></el-form-item><el-form-item label="实际跟进结果"><el-input v-model="edit.result" type="textarea" :rows="4" maxlength="2000" show-word-limit placeholder="记录实际发生的沟通、订单或核对结果" /></el-form-item></el-form><p class="decision-note">完成行动必须有结果和类型。填入“已充值”不代表到账，金额仍以账本为准。</p><template #footer><GlassButton @click="editOpen = false">取消</GlassButton><GlassButton variant="primary" :loading="editing" @click="submitEdit">保存结果</GlassButton></template></el-dialog>
</template>
<script setup>
import { onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import DecisionTable from './DecisionTable.vue'
import InsightCards from './InsightCards.vue'
import { domesticDecisionApi as api } from '@/api/domesticDecision'
import { useAuthStore } from '@/stores/auth'
import { currentBeijingDate, formatBeijingDateTime } from '@/utils/datetime'
import { confirmAction, isFeedbackCancelled, msgError, msgWarning } from '@/utils/feedback'
import { actionCompletionError, label, FIELD_LABELS, METRIC_LABELS } from '../state'
const props = defineProps({ data: Object, financeAllowed: Boolean, reportAllowed: Boolean, mutate: Function, failure: Function })
defineEmits(['evidence', 'customer', 'plan'])
const auth = useAuthStore(), actions = ref([]), actionsLoading = ref(false), actionsError = ref('')
const jobs = ref([]), question = ref(''), focus = ref('executive'), format = ref('csv'), pendingKind = ref(''), jobError = ref('')
const createOpen = ref(false), selectedInsight = ref(null), dueDate = ref(currentBeijingDate()), creating = ref(false), editOpen = ref(false), editing = ref(false), edit = reactive({})
const resultTypes = { contacted: '已联系', ordered: '观察到订单', recharged: '观察到充值', reconciled: '已核对账目', no_response: '未得到回应', other: '其他' }
const briefColumns = [{ key: 'amount', label: '相关整单额', format: 'money' }, { key: 'matched_amount', label: '匹配明细额', format: 'money' }, { key: 'order_count', label: '订单数', format: 'number' }, { key: 'customer_count', label: '当期购买客户', format: 'number' }]
const briefFinanceColumns = [{ key: 'recharge_amount', label: '充值', format: 'money' }, { key: 'net_order_deduction', label: '净扣款', format: 'money' }, { key: 'positive_balance', label: '正余额', format: 'money' }, { key: 'debt', label: '欠款', format: 'money' }]
let disposed = false
const timers = new Map(), attempts = new Map()
const storageKey = () => `domestic-decision-job-ids:${auth.user?.id}`
const kindPath = kind => ({ brief: 'briefs', export: 'exports', plan: 'query-plans' }[kind] || kind)
function remember() { try { sessionStorage.setItem(storageKey(), JSON.stringify(jobs.value.slice(0, 15).map(job => ({ id: job.id, kind: job.kind })))) } catch { /* IDs are an optional recovery aid */ } }
function customerName(id) { return props.data.customers.find(row => row.customer_id === id)?.shop_name || `客户 ${id}` }
async function loadActions() { actionsLoading.value = true; actionsError.value = ''; try { const rows = await api.actions(); if (!disposed) actions.value = rows } catch (cause) { actionsError.value = props.failure(cause) } finally { actionsLoading.value = false } }
function prepareAction(insight) { selectedInsight.value = insight; dueDate.value = currentBeijingDate(); createOpen.value = true }
defineExpose({ prepareAction })
async function submitAction() {
  if (!dueDate.value || creating.value) return
  creating.value = true
  try { await props.mutate(() => api.createAction({ run_id: selectedInsight.value.source_run_id || props.data.meta.run_id, customer_id: selectedInsight.value.customer_id, rule_key: selectedInsight.value.rule_key, request_key: crypto.randomUUID(), due_date: dueDate.value }), '内部行动已保存'); createOpen.value = false }
  catch { createOpen.value = false; msgWarning('请先检查行动列表，避免在结果不确定时重复创建') }
  finally { creating.value = false; await loadActions() }
}
function editAction(action) { Object.assign(edit, { id: action.id, expected_version: action.version, status: action.status, result: action.result || '', result_type: action.result_type || null }); editOpen.value = true }
async function submitEdit() {
  const invalid = actionCompletionError(edit); if (invalid) { msgWarning(invalid); return }
  editing.value = true
  try { const { id, ...body } = edit; await props.mutate(() => api.updateAction(id, body), '行动结果已保存'); editOpen.value = false } catch { editOpen.value = false } finally { editing.value = false; loadActions() }
}
function mergeJob(job) { const index = jobs.value.findIndex(row => row.id === job.id); if (index < 0) jobs.value.unshift(job); else jobs.value[index] = job; remember() }
async function refreshJob(job, polling = false) {
  if (disposed || !props.reportAllowed) return
  try {
    const result = await api.job(kindPath(job.kind), job.id); if (disposed) return
    mergeJob(result)
    if (['queued', 'running'].includes(result.status)) {
      const count = polling ? (attempts.get(job.id) || 0) + 1 : 0; attempts.set(job.id, count)
      if (count < 8) { clearTimeout(timers.get(job.id)); timers.set(job.id, setTimeout(() => refreshJob(result, true), Math.min(1000 * 2 ** count, 15000))) }
    } else { clearTimeout(timers.get(job.id)); timers.delete(job.id) }
  } catch (cause) { if (!disposed) { jobError.value = props.failure(cause); if ([403, 404].includes(cause.response?.status)) jobs.value = jobs.value.filter(row => row.id !== job.id); remember() } }
}
async function createJob(kind) {
  if (pendingKind.value || !props.reportAllowed) return
  pendingKind.value = kind; jobError.value = ''
  try { sessionStorage.setItem(`${storageKey()}:uncertain`, kind) } catch { /* optional request recovery lock */ }
  try {
    const body = { run_id: props.data.meta.run_id, request_key: crypto.randomUUID(), focus: focus.value, format: format.value, ...(kind === 'query-plans' ? { question: question.value.trim() } : {}) }
    const job = await api.createJob(kind, body)
    mergeJob(job); try { sessionStorage.removeItem(`${storageKey()}:uncertain`) } catch { /* optional recovery */ }
    if (!disposed) refreshJob(job)
  } catch (cause) {
    jobError.value = props.failure(cause)
    const status = cause.response?.status, confirmedFailure = status >= 400 && status < 500
    if (!confirmedFailure) jobError.value = '请求结果尚未确认，请先查看历史简报或联系管理员核验任务；本次不自动重复提交。'
    if (confirmedFailure) { pendingKind.value = ''; try { sessionStorage.removeItem(`${storageKey()}:uncertain`) } catch { /* optional recovery */ } }
    return
  }
  pendingKind.value = ''
}
async function loadBriefs() { if (!props.reportAllowed) return; try { const rows = await api.briefs(); if (!disposed) { rows.forEach(mergeJob); rows.filter(job => ['queued', 'running'].includes(job.status)).forEach(job => refreshJob(job)) } } catch (cause) { jobError.value = props.failure(cause) } }
async function acknowledgeUncertain() {
  try { await confirmAction('确认已在历史简报或后台核验上次任务？解除待确认状态后，下次点击生成将创建新的任务。', '核验生成任务'); sessionStorage.removeItem(`${storageKey()}:uncertain`); pendingKind.value = ''; jobError.value = '' }
  catch (cause) { if (!isFeedbackCancelled(cause)) msgError('无法解除待确认状态', cause) }
}
async function download(job) {
  try { const response = await api.download(job.id); const href = URL.createObjectURL(response.data); const link = document.createElement('a'); link.href = href; link.download = response.headers['content-disposition']?.match(/filename="?([^";]+)/)?.[1] || `domestic-decision-${job.id}.${format.value}`; link.click(); setTimeout(() => URL.revokeObjectURL(href), 1000) }
  catch (cause) { msgError(props.failure(cause), cause) }
}
watch(() => props.data.meta.run_id, loadActions)
watch(() => props.financeAllowed, allowed => { if (!allowed) { focus.value = 'executive'; jobs.value = [] } })
onMounted(() => { loadActions(); if (props.reportAllowed) { try { pendingKind.value = sessionStorage.getItem(`${storageKey()}:uncertain`) || ''; if (pendingKind.value) jobError.value = '上次生成请求尚未确认。请在历史简报或后台核验任务后再发起新请求，页面不会自动重复提交。'; const ids = JSON.parse(sessionStorage.getItem(storageKey()) || '[]'); ids.slice(0, 15).forEach(job => refreshJob(job)) } catch { /* invalid optional recovery metadata */ } } })
onBeforeUnmount(() => { disposed = true; timers.forEach(clearTimeout); timers.clear() })
</script>
