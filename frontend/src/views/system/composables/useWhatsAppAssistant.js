import { computed, onUnmounted, ref, watch } from 'vue'
import { formatBeijingDateTime, parseApiDateTime } from '@/utils/datetime'
import {
  getWhatsAppAssistantOptions, createWhatsAppAssistantRun, listWhatsAppAssistantRuns,
  getWhatsAppAssistantRun, getWhatsAppAssistantRequest, updateWhatsAppAssistantTask,
} from '@/api/whatsapp'

export const assistantStatuses = {
  pending: { label: '等待分析', type: 'warning' }, running: { label: '正在分析', type: 'warning' },
  succeeded: { label: '分析完成', type: 'success' }, failed: { label: '分析失败', type: 'danger' },
  stale: { label: '结果已失效', type: 'info' },
}
const unresolvedRequests = new Map()
const pendingStatuses = ['pending', 'running']
export function defaultAssistantRange(now = new Date()) {
  return [formatBeijingDateTime(new Date(now.getTime() - 7 * 86400000)), formatBeijingDateTime(now)]
}
export function assistantRangeError(range, maxDays = 31) {
  if (!Array.isArray(range) || range.length !== 2) return '请选择开始和结束时间'
  const start = parseApiDateTime(range[0]), end = parseApiDateTime(range[1])
  if (!start || !end) return '请选择有效的北京时间'
  if (start > end) return '结束时间不能早于开始时间'
  if (end - start > maxDays * 86400000) return `每次最多分析 ${maxDays} 天`
  return ''
}

function errorText(error, fallback) {
  const detail = error?.response?.data?.detail
  return typeof detail === 'string' ? detail : error?.response?.data?.message || fallback
}

export function useWhatsAppAssistant(props, close) {
  const options = ref(null), runs = ref([]), run = ref(null), range = ref(defaultAssistantRange())
  const scope = ref('all'), selectedRunUid = ref(''), loading = ref(false), submitting = ref(false)
  const error = ref(''), unresolvedUid = ref(''), unresolvedTarget = ref(''), canRetryRequest = ref(false), taskBusy = ref('')
  let epoch = 0, timer, disposed = false, controller = new AbortController(), runSequence = 0
  const contextKey = computed(() => `${props.accessKey}:${props.account?.account_uid || ''}`)
  const rangeError = computed(() => assistantRangeError(range.value, options.value?.limits?.max_days || 31))
  const isRunning = computed(() => pendingStatuses.includes(run.value?.status))
  const canCreate = computed(() => options.value?.can_analyze && !rangeError.value && !loading.value
    && !submitting.value && !isRunning.value && !unresolvedUid.value && !taskBusy.value
    && (scope.value === 'all' || Boolean(props.conversation?.conversation_uid)))
  const active = id => !disposed && props.modelValue && id === epoch
  const config = () => ({ signal: controller.signal, suppressToast: true, suppressNotFound: true, showLoading: false })
  function reset() {
    epoch++; runSequence++; clearTimeout(timer); controller.abort(); controller = new AbortController()
    loading.value = false; submitting.value = false; taskBusy.value = ''; options.value = null
    run.value = null; runs.value = []; error.value = ''; selectedRunUid.value = ''; unresolvedUid.value = ''
    unresolvedTarget.value = ''; canRetryRequest.value = false
  }
  function acceptRun(value) {
    run.value = value; selectedRunUid.value = value.run_uid
    const index = runs.value.findIndex(item => item.run_uid === value.run_uid)
    if (index < 0) runs.value = [value, ...runs.value].slice(0, 10)
    else runs.value = runs.value.map(item => item.run_uid === value.run_uid ? value : item)
  }
  function schedule(id, sequence) {
    clearTimeout(timer)
    if (active(id) && sequence === runSequence && isRunning.value) timer = setTimeout(() => refreshRun(), 3000)
  }
  async function selectRun(uid) {
    const id = epoch, sequence = ++runSequence
    clearTimeout(timer); run.value = null; selectedRunUid.value = uid; error.value = ''
    if (!uid) return
    loading.value = true
    try {
      const response = await getWhatsAppAssistantRun(uid, config())
      if (!active(id) || sequence !== runSequence) return
      acceptRun(response.data); schedule(id, sequence)
    } catch (failure) {
      if (active(id) && sequence === runSequence) error.value = errorText(failure, '暂时无法读取报告，请重试')
    } finally { if (active(id) && sequence === runSequence) loading.value = false }
  }
  function refreshRun() { return selectRun(selectedRunUid.value) }
  async function lookupRequest() {
    if (!unresolvedUid.value || submitting.value) return
    const id = epoch, uid = unresolvedUid.value, key = contextKey.value
    submitting.value = true; error.value = ''; canRetryRequest.value = false
    try {
      const response = await getWhatsAppAssistantRequest(uid, props.account.account_uid, config())
      if (!active(id)) return
      unresolvedRequests.delete(key); unresolvedUid.value = ''; unresolvedTarget.value = ''; acceptRun(response.data)
      if (pendingStatuses.includes(response.data.status)) schedule(id, ++runSequence)
      else await selectRun(response.data.run_uid)
    } catch (failure) {
      if (active(id)) {
        canRetryRequest.value = failure?.response?.status === 404
        error.value = canRetryRequest.value ? '暂未找到提交记录。可继续查询，或用原参数重新提交本次分析。'
          : errorText(failure, '提交结果仍未确认，请稍后查询提交状态')
      }
    } finally { if (active(id)) submitting.value = false }
  }
  async function initialize() {
    reset()
    if (!props.modelValue || !props.account?.can_read_body) return
    const id = epoch
    scope.value = 'all'; range.value = defaultAssistantRange()
    const original = unresolvedRequests.get(contextKey.value)
    unresolvedUid.value = original?.payload.client_request_uid || ''
    if (original) {
      range.value = [formatBeijingDateTime(original.payload.start_at), formatBeijingDateTime(original.payload.end_at)]
      scope.value = original.payload.conversation_uid ? 'current' : 'all'
      unresolvedTarget.value = original.target
    }
    loading.value = true
    const results = await Promise.allSettled([
      getWhatsAppAssistantOptions(props.account.account_uid, config()),
      listWhatsAppAssistantRuns(props.account.account_uid, config()),
    ])
    if (!active(id)) return
    if (results[0].status === 'fulfilled') options.value = results[0].value.data
    else error.value = errorText(results[0].reason, '暂时无法读取助手配置，请重新打开')
    if (results[1].status === 'fulfilled') runs.value = results[1].value.data?.items || []
    else error.value = errorText(results[1].reason, '暂时无法读取历史报告，请重新打开')
    loading.value = false
    const configurationError = error.value
    if (unresolvedUid.value) await lookupRequest()
    else if (runs.value.length) await selectRun(runs.value[0].run_uid)
    if (active(id) && configurationError && !error.value) error.value = configurationError
  }
  async function createRun() {
    if (!canCreate.value) return
    const uid = crypto.randomUUID()
    const payload = { account_uid: props.account.account_uid, conversation_uid: scope.value === 'current'
      ? props.conversation?.conversation_uid || null : null,
    start_at: `${range.value[0].replace(' ', 'T')}+08:00`, end_at: `${range.value[1].replace(' ', 'T')}+08:00`, client_request_uid: uid }
    const target = scope.value === 'current' ? props.conversation?.contact_name || props.conversation?.contact_phone || props.conversation?.chat_id || props.conversation?.conversation_uid : '整个账号'
    unresolvedRequests.set(contextKey.value, { payload, target }); unresolvedUid.value = uid; unresolvedTarget.value = target
    await submitPayload(payload)
  }
  async function retryRequest() {
    if (!canRetryRequest.value || submitting.value || loading.value || !options.value?.can_analyze) return
    const original = unresolvedRequests.get(contextKey.value)
    if (original?.payload.client_request_uid !== unresolvedUid.value) return
    await submitPayload(original.payload)
  }
  async function submitPayload(payload) {
    const id = epoch, key = contextKey.value
    submitting.value = true; error.value = ''; canRetryRequest.value = false
    try {
      const response = await createWhatsAppAssistantRun(payload, config())
      unresolvedRequests.delete(key)
      if (!active(id)) return
      unresolvedUid.value = ''; unresolvedTarget.value = ''; acceptRun(response.data)
      if (pendingStatuses.includes(response.data.status)) schedule(id, ++runSequence)
      else await selectRun(response.data.run_uid)
    } catch (failure) {
      if (!active(id)) return
      const status = failure?.response?.status
      if ([400, 401, 403, 422].includes(status)) {
        unresolvedRequests.delete(key); unresolvedUid.value = ''; unresolvedTarget.value = ''
        error.value = errorText(failure, '无法开始分析，请检查授权与时间范围')
      } else {
        submitting.value = false
        await lookupRequest()
      }
    } finally { if (active(id)) submitting.value = false }
  }
  async function setTaskCompleted(task, completed) {
    if (!run.value || taskBusy.value || run.value.status !== 'succeeded') return
    const id = epoch, uid = run.value.run_uid, sequence = runSequence
    taskBusy.value = task.task_uid; error.value = ''
    try {
      const response = await updateWhatsAppAssistantTask(uid, task.task_uid, completed, config())
      if (active(id) && sequence === runSequence) acceptRun(response.data)
    } catch (failure) {
      if (active(id) && sequence === runSequence) {
        const status = failure?.response?.status
        if (status === 409) {
          run.value = null
          await selectRun(uid)
        } else {
          if ([403, 404].includes(status)) run.value = null
          error.value = errorText(failure, '清单更新未确认，请刷新报告核对后再操作')
        }
      }
    } finally { if (active(id)) taskBusy.value = '' }
  }
  watch(() => props.modelValue, visible => { if (visible) void initialize(); else reset() }, { immediate: true })
  watch(() => [contextKey.value, props.account?.can_read_body, props.account?.consent_version,
    props.account?.consent_state, props.account?.ai_egress_allowed], () => { reset(); if (props.modelValue) close() })
  onUnmounted(() => { disposed = true; reset() })
  return { options, runs, run, range, scope, selectedRunUid, loading, submitting, error, unresolvedUid, unresolvedTarget, canRetryRequest,
    taskBusy, rangeError, isRunning, canCreate, selectRun, refreshRun, lookupRequest, createRun, retryRequest, setTaskCompleted }
}
