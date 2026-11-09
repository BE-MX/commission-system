<template>
  <section v-if="details.handoff || actions.length || details.coordination_reasons?.length" class="collaboration-panel">
    <template v-if="details.handoff">
      <h3>{{ details.handoff.kind === 'request' ? '接手申请' : '交接包' }}</h3>
      <p>{{ [details.handoff.recipient_name, details.handoff.created_at].filter(Boolean).join(' · ') }}</p>
      <dl class="handoff-summary">
        <template v-for="field in handoffFields" :key="field.key">
          <div v-if="details.handoff[field.key]"><dt>{{ field.label }}</dt><dd>{{ details.handoff[field.key] }}</dd></div>
        </template>
      </dl>
      <ul v-if="Array.isArray(details.handoff.tasks) && details.handoff.tasks.length" class="handoff-tasks">
        <li v-for="task in details.handoff.tasks" :key="task.id || task.task_id">
          {{ task.title || `待办 #${task.id || task.task_id || task}` }}<template v-if="task.due_date"> · {{ task.due_date }}</template>
        </li>
      </ul>
      <ul v-if="details.handoff.selected_records?.length" class="handoff-tasks">
        <li v-for="record in details.handoff.selected_records" :key="record.id">{{ record.date }} · {{ record.summary }}</li>
      </ul>
    </template>
    <p v-if="details.coordination_reasons?.length" class="coordination-reason">需协调 · {{ details.coordination_reasons.map(reason => labelFor(COORDINATION_REASON, reason)).join('、') }}</p>
    <div class="collaboration-actions">
      <GlassButton v-for="action in actions" :key="action" v-any-permission="actionPermissions(action)"
                   :variant="['accept_handoff', 'claim'].includes(action) ? 'primary' : 'outline'" @click="open(action)">
        {{ actionLabel(action) }}
      </GlassButton>
    </div>
  </section>

  <el-dialog v-model="visible" :title="actionLabel(action)" width="640px" append-to-body destroy-on-close
             :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving" @closed="clearDialog">
    <el-form v-loading="loading" :disabled="saving || uncertain" label-position="top" @submit.prevent="submit">
      <p v-if="action === 'claim'">接手后，你将成为当前跟进人。</p>
      <p v-if="action === 'offer_handoff'">接收人接受前，由你继续负责跟进。</p>
      <p v-if="action === 'accept_handoff'">确认后，当前跟进人和选定的待办将一起转交。</p>
      <p v-if="closingResponsibility">请逐条核对开发待办。需要继续推进的计划，可先发起交接。</p>
      <el-form-item v-if="needsCandidate" :label="action === 'add_collaborator' ? '协作人' : '接收人'" required>
        <el-select v-model="form.person" filterable aria-label="选择人员" class="full">
          <el-option v-for="person in candidates" :key="person.user_id" :value="person.user_id" :label="person.name" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="action === 'remove_collaborator'" label="协作人" required>
        <el-select v-model="form.person" filterable aria-label="选择协作人" class="full">
          <el-option v-for="person in details.collaborators" :key="person.user_id" :value="person.user_id" :label="person.name" />
        </el-select>
      </el-form-item>
      <el-form-item v-if="needsReason" label="原因" required><el-input v-model="form.reason" type="textarea" maxlength="500" /></el-form-item>
      <el-form-item v-if="needsSummary" label="交接摘要" required><el-input v-model="form.summary" type="textarea" maxlength="2000" /></el-form-item>
      <template v-if="needsSummary">
        <el-form-item v-for="field in handoffFields.slice(2)" :key="field.key" :label="field.label">
          <el-input v-model="form[field.key]" type="textarea" maxlength="500" />
        </el-form-item>
        <el-form-item v-if="action === 'offer_handoff' && shareableRecords.length" label="随交接附上已共享的记录">
          <el-checkbox-group v-model="form.recordIds" class="record-options">
            <el-checkbox v-for="record in shareableRecords" :key="record.id" :value="record.id" class="record-option">
              {{ record.followup_date }} · {{ record.shared_summary }}
            </el-checkbox>
          </el-checkbox-group>
        </el-form-item>
      </template>
      <el-form-item v-if="action === 'stop'" label="后续是否允许联系">
        <el-radio-group v-model="form.allowFutureContact">
          <el-radio :value="false">不再联系</el-radio>
          <el-radio :value="true">获授权恢复后可联系</el-radio>
        </el-radio-group>
      </el-form-item>
      <section v-if="tasks.length" class="task-decisions">
        <h3>未完成待办</h3>
        <div v-for="task in tasks" :key="task.id" class="task-decision">
          <div><strong>{{ task.title }}</strong><p>{{ [labelFor(taskTypes, task.task_type), labelFor(taskPurposes, task.purpose, '未分类'), task.due_date].filter(Boolean).join(' · ') }}</p></div>
          <span v-if="task.decision === 'retain'">保留原处理人</span>
          <el-select v-else v-model="form.taskChoices[task.id]" :aria-label="`处理 ${task.title}`" placeholder="请选择">
            <el-option v-for="option in choices(task)" :key="option.key" :value="option.key" :label="option.label" />
          </el-select>
        </div>
      </section>
      <el-alert v-if="error" type="error" :title="error" :closable="false" show-icon />
      <GlassButton v-if="conflict" variant="link" @click="reload">刷新当前责任</GlassButton>
    </el-form>
    <template #footer>
      <GlassButton :disabled="saving" @click="visible = false">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" :disabled="!canSubmit" @click="submit">{{ uncertain ? '重试确认' : '确认' }}</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgSuccessText } from '@/utils/feedback'
import { COLLABORATION_ACTION, COORDINATION_REASON, labelFor } from '../customerOverview'
import { newRequestId } from '../followupDraft'

const props = defineProps({ details: { type: Object, required: true }, shareableRecords: { type: Array, default: () => [] } })
const emit = defineEmits(['updated'])
const visible = ref(false), action = ref(''), error = ref(''), conflict = ref(false)
const uncertain = ref(false), loadFailed = ref(false)
const loading = ref(false), saving = ref(false), candidates = ref([]), tasks = ref([])
const form = reactive({})
let requestId
let retryBody
let generation = 0
const handoffFields = [
  { key: 'reason', label: '交接原因' }, { key: 'summary', label: '交接摘要' }, { key: 'obstacle', label: '当前障碍' },
  { key: 'commitment', label: '已承诺事项' }, { key: 'next_step', label: '建议下一步' },
]
const taskTypes = { plan: '约定跟进', receipt: '收货回访', issue: '异常意见' }
const taskPurposes = { development: '开发', maintenance: '维护', other: '其他' }
const coordinatorActions = ['open', 'reassign', 'reopen']
const responseActions = ['accept_handoff', 'reject_handoff', 'withdraw_handoff']
const actions = computed(() => (props.details.available_actions || []).filter(key => key in COLLABORATION_ACTION))
const requestApproval = computed(() => action.value === 'accept_handoff' && props.details.handoff?.kind === 'request')
const needsCandidate = computed(() => ['offer_handoff', 'reassign', 'add_collaborator'].includes(action.value))
const needsReason = computed(() => ['offer_handoff', 'request_handoff', 'reject_handoff', 'release', 'open', 'reassign', 'stop', 'reopen'].includes(action.value))
const needsSummary = computed(() => action.value === 'offer_handoff' || requestApproval.value)
const closingResponsibility = computed(() => ['release', 'stop'].includes(action.value))
const needsTasks = computed(() => ['offer_handoff', 'reassign', 'release', 'stop'].includes(action.value) || requestApproval.value)
const canSubmit = computed(() => visible.value && !loading.value && !saving.value && !conflict.value && !loadFailed.value &&
  (!needsReason.value || form.reason.trim()) && (!needsSummary.value || form.summary.trim()) &&
  (!(needsCandidate.value || action.value === 'remove_collaborator') || form.person) &&
  tasks.value.every(task => task.decision === 'retain' || form.taskChoices[task.id]))
function actionPermissions(key) {
  if (coordinatorActions.includes(key)) return ['domestic_followup:coordinate']
  if (['stop', 'withdraw_handoff'].includes(key)) return ['domestic_followup:write', 'domestic_followup:coordinate']
  return ['domestic_followup:write']
}
const actionLabel = key => key === 'accept_handoff' && props.details.handoff?.kind === 'request' ? '同意接手申请' : labelFor(COLLABORATION_ACTION, key)

function choices(task) {
  const keep = { key: 'keep', label: '保留原处理人' }
  const transfer = { key: 'transfer', label: '转交' }
  const cancel = { key: 'cancel', label: '取消待办' }
  if (closingResponsibility.value) {
    return task.decision === 'transfer' ? [cancel] : [keep, cancel]
  }
  if (task.decision === 'transfer') return [transfer]
  return [keep, transfer]
}
function clearDialog() {
  if (visible.value) return
  generation++
  loading.value = false
  tasks.value = []
  candidates.value = []
}
async function open(key) {
  const run = ++generation
  action.value = key
  error.value = ''
  conflict.value = false
  uncertain.value = false
  loadFailed.value = false
  retryBody = null
  candidates.value = []
  tasks.value = []
  requestId = newRequestId()
  Object.assign(form, { person: null, reason: '', summary: '', obstacle: '', commitment: '', next_step: '', allowFutureContact: false, taskChoices: {}, recordIds: [] })
  visible.value = true
  if (!needsCandidate.value && !needsTasks.value) return
  loading.value = true
  try {
    const [people, taskSet] = await Promise.all([
      needsCandidate.value ? followupApi.collaborationCandidates(props.details.customer_id) : [],
      needsTasks.value ? followupApi.collaborationTasks(props.details.customer_id, key) : { items: [] },
    ])
    if (run !== generation || !visible.value) return
    candidates.value = people
    tasks.value = taskSet.items
    for (const task of tasks.value) {
      if (task.decision === 'transfer' && !closingResponsibility.value) form.taskChoices[task.id] = 'transfer'
      if (task.decision === 'optional') form.taskChoices[task.id] = 'keep'
    }
    if (needsCandidate.value && !candidates.value.length) error.value = '没有符合该客户协作范围的人员'
  } catch (failure) {
    if (run === generation) {
      loadFailed.value = true
      error.value = message(failure, '操作资料加载失败')
    }
  } finally {
    if (run === generation) loading.value = false
  }
}
function message(failure, fallback) {
  const detail = apiError(failure, fallback)
  return typeof detail === 'string' ? detail : detail.message || fallback
}
async function submit() {
  if (!canSubmit.value) return
  const key = action.value
  const body = { action: key, version: props.details.version, idempotency_key: requestId }
  if (needsReason.value) body.reason = form.reason.trim()
  if (needsSummary.value) for (const field of handoffFields.slice(1)) body[field.key] = form[field.key].trim()
  if (['offer_handoff', 'reassign'].includes(key)) body.recipient_user_id = form.person
  if (key === 'offer_handoff') body.selected_record_ids = form.recordIds
  if (['add_collaborator', 'remove_collaborator'].includes(key)) body.collaborator_user_id = form.person
  if (responseActions.includes(key)) Object.assign(body, { handoff_id: props.details.handoff.id, handoff_version: props.details.handoff.version })
  if (key === 'stop') body.allow_future_contact = form.allowFutureContact
  if (needsTasks.value) {
    for (const choice of ['transfer', 'keep', 'cancel']) {
      body[`${choice}_task_ids`] = tasks.value.filter(task => form.taskChoices[task.id] === choice && (choice !== 'keep' || task.decision === 'choose')).map(task => task.id)
    }
  }
  saving.value = true
  error.value = ''
  try {
    retryBody ||= body
    await followupApi.collaborationAction(props.details.customer_id, retryBody)
    msgSuccessText(`已完成${actionLabel(key)}`)
    reload()
  } catch (failure) {
    error.value = message(failure, '操作失败，请核对当前责任后重试')
    const status = failure?.response?.status
    conflict.value = status === 409
    uncertain.value = !status || status >= 500
    if (uncertain.value) error.value += '。结果尚未确认，可重试同一次提交。'
    else retryBody = null
  } finally { saving.value = false }
}
function reload() {
  visible.value = false
  emit('updated')
}
defineExpose({ open })
</script>

<style scoped>
.collaboration-panel { margin: 12px 0; padding: 12px; border: 1px solid var(--border-color); border-radius: 12px; }
.collaboration-panel h3, .task-decisions h3 { margin: 0 0 8px; }
.collaboration-panel p { margin: 0 0 8px; }
.handoff-summary { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.handoff-summary dt, .task-decision p { margin: 0; font-size: 12px; color: var(--text-secondary); }
.handoff-summary dd { margin: 2px 0 0; overflow-wrap: anywhere; white-space: pre-wrap; }
.handoff-tasks { padding-left: 20px; }
.collaboration-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.coordination-reason { color: var(--color-warning-text); }
.task-decisions { margin-bottom: 12px; }
.task-decision { display: grid; grid-template-columns: minmax(0, 1fr) minmax(100px, 155px); gap: 8px; align-items: center; padding: 8px 0; border-top: 1px solid var(--border-color); }
.full { width: 100%; }
.record-options { display: grid; }
.record-option { height: auto; white-space: normal; }
</style>
