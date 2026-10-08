<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { useListPage } from '@/composables/useListPage'
import { useAuthStore } from '@/stores/auth'
import { portalAdminApi } from '@/api/portal'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import { createNotificationCommand, deliveryStatuses, notificationEvents, notificationErrors } from './notificationDelivery.mjs'

const props = defineProps({ requestId: { type: String, default: '' }, accessId: { type: String, default: '' } })
const mapping = !!props.accessId
const objectId = computed(() => mapping ? props.accessId : props.requestId)
const receiptField = mapping ? 'access_id' : 'request_id'
const writePermission = mapping ? 'portal_mapping:write' : 'portal_order:write'
const deliveryNotice = mapping ? '映射已发布，通知投递失败不影响显示名称。已分发子任务不代表邮件已发送；重新排队仍须检查当前客户权限，邮件可能重复。' : '已分发子任务不代表邮件已发送。失败通知不影响订单；重新排队仍需检查收件人当前权限，邮件可能重复。'
const emit = defineEmits(['close', 'busy'])
const auth = useAuthStore(), error = ref(''), selected = ref(null), reason = ref(''), confirmed = ref(false), state = ref('idle')
const errorSummary = ref(null), noticeSummary = ref(null), retryReason = ref(null), table = ref(null), notice = ref('')
let feedbackSequence = 0
async function focusFeedback(target) {
  const current = ++feedbackSequence
  await nextTick()
  if (!disposed && current === feedbackSequence) target.value?.$el?.focus()
}
async function showError(value) { error.value = value; await focusFeedback(errorSummary) }
async function showNotice(value) { notice.value = value; await focusFeedback(noticeSummary) }
const busy = computed(() => ['sending', 'uncertain'].includes(state.value))
watch(busy, value => emit('busy', value), { immediate: true, flush: 'sync' })
const command = createNotificationCommand(value => mapping ? portalAdminApi.retryMappingNotification(value) : portalAdminApi.retryNotification(value), { scope: mapping ? 'mapping' : 'order' })
let generation = 0, controller, disposed = false
const message = e => e?.response?.data?.message || (e?.code === 'ERR_NETWORK' ? '网络连接中断，请按页面提示核对。' : e.message) || '通知状态读取失败，请重试。'
const { list, total, page, pageSize, loading, fetchList, handlePageChange } = useListPage(async params => {
  const current = ++generation
  controller?.abort(); controller = new AbortController()
  list.value = []; total.value = 0; selected.value = null; reason.value = ''; confirmed.value = false; error.value = ''; notice.value = ''
  try {
    const result = await (mapping ? portalAdminApi.mappingNotifications(objectId.value, params, controller.signal) : portalAdminApi.notifications(objectId.value, params, controller.signal))
    if (disposed || current !== generation) return { items: [], total: 0 }
    if (result?.[receiptField] !== objectId.value || !Array.isArray(result.items)) throw new Error('通知回执不完整，请刷新。')
    void showNotice('已读取当前通知投递记录。')
    return result
  } catch (e) {
    if (!disposed && current === generation) void showError(message(e))
    return { items: [], total: 0 }
  }
})
watch(list, async () => {
  await nextTick()
  if (disposed) return
  const scroll = table.value?.$el?.querySelector('.el-scrollbar__wrap')
  if (scroll) { scroll.tabIndex = 0; scroll.setAttribute('role', 'region'); scroll.setAttribute('aria-label', '通知投递列表，可用方向键横向滚动') }
}, { flush: 'post' })
async function select(row) {
  if (busy.value || loading.value || !row.retry_eligible) return
  selected.value = row; reason.value = ''; confirmed.value = false; error.value = ''; notice.value = ''
  const current = ++feedbackSequence
  await nextTick()
  if (!disposed && current === feedbackSequence && selected.value?.id === row.id && !busy.value) retryReason.value?.focus()
}
watch(reason, () => { confirmed.value = false }, { flush: 'sync' })
async function submit(replay = false) {
  if (state.value === 'sending' || loading.value) return
  let value
  if (!replay) {
    if (busy.value || !selected.value || !confirmed.value || !reason.value.trim()) return
    value = { id: objectId.value, eventId: selected.value.id, key: crypto.randomUUID(), body: { fingerprint: selected.value.fingerprint, reason: reason.value.trim() } }
  }
  error.value = ''; notice.value = ''
  try {
    const promise = command.execute(value); state.value = command.state
    const result = await promise
    if (!result) return
    state.value = command.state
    msgSuccess('通知已重新排队')
    await fetchList()
    if (!disposed && !error.value) await showNotice('通知已重新排队，请核对当前投递记录。')
  } catch (e) {
    state.value = command.state; void showError(message(e))
    if ([401, 403, 404].includes(e?.response?.status)) {
      list.value = []; total.value = 0; selected.value = null; reason.value = ''; confirmed.value = false
    }
  }
}
function close() { if (!busy.value) emit('close') }
function clear() { disposed = true; feedbackSequence++; generation++; controller?.abort(); command.clear(); list.value = []; total.value = 0; selected.value = null; reason.value = ''; confirmed.value = false }
watch(() => [auth.accessToken, auth.user, props.requestId, props.accessId], () => { clear(); emit('close') })
function beforeUnload(event) { if (busy.value) { event.preventDefault(); event.returnValue = '' } }
window.addEventListener('beforeunload', beforeUnload)
onBeforeUnmount(() => { emit('busy', false); clear(); window.removeEventListener('beforeunload', beforeUnload) })
onBeforeRouteLeave(() => !busy.value)
</script>

<template>
  <el-dialog :model-value="true" title="通知投递记录" width="820px" class="portal-notification-dialog" :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy" @update:model-value="value => { if (!value) close() }">
    <p v-if="loading || state === 'sending'" role="status" class="notification-status">{{ loading ? '正在读取通知投递记录…' : '正在重新排队通知，请等待回执…' }}</p>
    <div class="notification-content" :aria-busy="loading || state === 'sending' || undefined">
    <el-alert :title="deliveryNotice" type="info" :closable="false" />
    <el-alert v-if="error" ref="errorSummary" tabindex="-1" :title="error" type="error" :closable="false" />
    <el-alert v-if="notice" ref="noticeSummary" tabindex="-1" :title="notice" type="info" :closable="false" />
    <el-alert v-if="state === 'uncertain'" title="重试结果待核对。请勿关闭或刷新浏览器，只重放原命令获取回执。" type="warning" :closable="false" />
    <el-table ref="table" v-loading="loading" :data="list" border class="list-table" empty-text="暂无可查看的业务通知">
      <el-table-column label="事件 / 接收方" min-width="160"><template #default="{ row }"><strong>{{ notificationEvents[row.event_type] || '业务通知' }}</strong><div>{{ row.recipient_kind === 'staff' ? '当前负责人' : row.recipient_kind === 'customer' ? '客户成员' : '业务源事件' }}</div><small>{{ formatBeijingDateTime(row.created_at) }}</small></template></el-table-column>
      <el-table-column label="投递情况" min-width="190"><template #default="{ row }"><el-tag effect="plain">{{ deliveryStatuses[row.status] || '状态待核对' }}</el-tag><p>本轮尝试 {{ row.attempt_count }} 次</p><small v-if="row.error_code">{{ notificationErrors[row.error_code] || '投递失败，请核对配置' }}</small><small v-if="row.next_attempt_at">下次尝试：{{ formatBeijingDateTime(row.next_attempt_at) }}</small></template></el-table-column>
      <el-table-column label="操作" min-width="110" fixed="right" class-name="table-action-column"><template #default="{ row }"><GlassButton v-if="row.retry_eligible" v-permission="writePermission" variant="link" :disabled="busy || loading" @click="select(row)">申请重试</GlassButton><span v-else>—</span></template></el-table-column>
    </el-table>
    <el-pagination :current-page="page" :page-size="pageSize" :total="total" :disabled="busy || loading" layout="total, prev, pager, next" @current-change="handlePageChange" />
    <el-form v-if="selected" label-position="top" :disabled="busy || loading" class="retry-form">
      <p>恢复 {{ notificationEvents[selected.event_type] || '业务通知' }} · {{ formatBeijingDateTime(selected.created_at) }}</p>
      <el-form-item label="重试原因"><el-input ref="retryReason" v-model="reason" aria-label="通知重试原因" type="textarea" maxlength="500" show-word-limit placeholder="例如：邮件服务已恢复；请勿填写密码或客户个人资料" /></el-form-item>
      <el-checkbox v-model="confirmed" :disabled="busy || loading">已核对失败原因，确认重新排队；不会修改映射、订单或 PI</el-checkbox>
    </el-form>
    </div>
    <template #footer><GlassButton :disabled="busy" @click="close">关闭</GlassButton><GlassButton :disabled="busy || loading" @click="fetchList">刷新投递记录</GlassButton><GlassButton v-if="state === 'uncertain'" v-permission="writePermission" variant="primary" @click="submit(true)">重放原重试命令</GlassButton><GlassButton v-else v-permission="writePermission" variant="primary" :loading="state === 'sending'" :disabled="busy || loading || !selected || !confirmed || !reason.trim()" @click="submit()">确认重新排队</GlassButton></template>
  </el-dialog>
</template>

<style scoped>
.notification-status { color: var(--text-secondary); line-height: 1.6; }
:deep(.list-table .cell) { white-space: normal !important; word-break: normal !important; overflow-wrap: anywhere; }
.el-alert { margin-bottom: 16px; }
.el-pagination { margin: 16px 0; overflow-x: auto; }
.retry-form { border-top: 1px solid var(--border-color); padding-top: 16px; }
p { margin: 8px 0; overflow-wrap: anywhere; }
small { display: block; color: var(--text-secondary); }
.el-checkbox { height: auto; white-space: normal; }
:deep(.el-checkbox__label) { white-space: normal; }
</style>
