<template>
  <DetailDrawer :model-value="visible" :title="data?.customer.shop_name || selected?.shop_name || '客户跟进'"
                width="640px" :loading="loading" @update:model-value="value => { if (!value) close() }">
    <div v-if="data || selected || collaboration" class="timeline">
      <dl v-if="selected || collaboration" class="tl-head">
        <div v-if="selected"><dt>地区</dt><dd>{{ regionLabel(selected) }}</dd></div>
        <div v-if="selected"><dt>成交情况</dt><dd>{{ dealLabel(selected) }} <template v-if="selected.deal_source">· {{ labelFor(DEAL_SOURCE, selected.deal_source) }}</template></dd></div>
        <div v-if="selected?.first_deal_date"><dt>首次成交</dt><dd>{{ selected.first_deal_date }}</dd></div>
        <div v-if="selected?.owner_name && selected.owner_name !== assignee"><dt>归属销售</dt><dd>{{ selected.owner_name }}</dd></div>
        <div><dt>{{ selected?.owner_name && selected.owner_name === assignee ? '归属及当前跟进人' : '当前跟进人' }}</dt><dd>{{ assignee || '暂无' }}</dd></div>
        <div><dt>协作状态</dt><dd>{{ labelFor(COLLABORATION_STATUS, collaboration?.state || selected?.collaboration_status) }}</dd></div>
        <div v-if="collaboration?.collaborators?.length"><dt>协作人</dt><dd>{{ collaboration.collaborators.map(person => person.name).join('、') }}</dd></div>
        <div><dt>开发进度</dt><dd>{{ labelFor(DEVELOPMENT_STAGE, collaboration?.stage || selected?.stage) }}</dd></div>
        <div><dt>下次安排</dt><dd>{{ collaboration?.next_plan_date || selected?.next_date || '未安排' }}</dd></div>
      </dl>
      <dl v-if="selected?.can_view_contacts" class="tl-head">
        <div><dt>联系人</dt><dd>{{ selected.contact || '待补' }}</dd></div>
        <div v-for="field in contactFields" :key="field.key">
          <dt>{{ field.label }}</dt>
          <dd><GlassButton v-if="selected[field.key]" variant="link" left-icon="CopyDocument" @click="copy(selected[field.key])">{{ selected[field.key] }}</GlassButton><template v-else>待补</template></dd>
        </div>
      </dl>
      <p v-if="selected?.can_view_contacts === false" class="tl-meta">{{ selected.collaboration_status === 'open' ? '接手后可查看联系方式' : '联系方式受限' }}</p>
      <CustomerSummaryActions v-if="selected" :key="customerId" :customer="selected" @updated="collaborationUpdated" />
      <section v-if="selected?.last_followup_summary || selected?.obstacles?.length" class="tl-section">
        <h3>接手摘要</h3>
        <p v-if="selected.last_followup_summary">{{ selected.last_followup_summary }}</p>
        <p v-if="selected.obstacles?.length">主要障碍 · {{ selected.obstacles.join('、') }}</p>
      </section>
      <CollaborationPanel v-if="collaboration" ref="collaborationPanel" :key="customerId" :details="collaboration"
                          :shareable-records="shareableRecords" @updated="collaborationUpdated" />
      <dl v-if="data" class="tl-head">
        <div><dt>等级</dt><dd>{{ data.customer.customer_level || '—' }}</dd></div>
        <div><dt>上次跟进</dt><dd :class="{ overdue: isOverdue }">{{ lastLabel }}</dd></div>
        <div><dt>跟进频率</dt><dd>{{ data.customer.frequency_days ? `每 ${data.customer.frequency_days} 天` : '未设' }}</dd></div>
        <div><dt>未结异常</dt><dd>{{ data.open_items.length }}</dd></div>
      </dl>
      <GlassButton v-if="data?.customer.writable || selected?.can_record" v-permission="'domestic_followup:write'" variant="primary" class="tl-record"
                   @click="record">记一条跟进</GlassButton>
      <GlassButton v-if="data?.customer.can_record_history" v-permission="'domestic_followup:write'" variant="link" class="tl-record"
                   @click="record(true)">历史补录</GlassButton>
      <section v-if="openTasks.length" class="tl-section">
        <h3>未完成事项</h3>
        <ul class="tl-items">
          <li v-for="task in openTasks" :key="task.id">{{ task.title }} · {{ task.assignee_name || '待分配' }} · {{ task.due_date }}</li>
        </ul>
      </section>
      <section v-if="data || collaboration" class="tl-section">
        <h3>历史时间线</h3>
        <el-select v-model="eventType" aria-label="事件类型" class="tl-filter" @change="loadEventsForType">
          <el-option v-if="data" label="全部沟通与发货" value="all" />
          <el-option v-if="data" label="沟通记录" value="followup" />
          <el-option v-if="data?.customer.shipment_readable" label="发货" value="shipment" />
          <el-option v-if="collaboration" label="协作事件" value="collaboration" />
        </el-select>
      </section>
      <el-timeline v-if="eventType === 'collaboration'">
        <el-timeline-item v-for="event in collaborationEvents" :key="event.id" :timestamp="formatBeijingDateTime(event.created_at)" placement="top">
          <p class="tl-summary">{{ labelFor(COLLABORATION_ACTION, event.action || event.kind) }}</p>
          <p class="tl-meta">{{ [event.actor_name, event.reason].filter(Boolean).join(' · ') }}</p>
          <p v-if="event.handoff_outcome" class="tl-meta">
            交接结果 · {{ labelFor(HANDOFF_OUTCOME, event.handoff_outcome.status) }}
          </p>
        </el-timeline-item>
      </el-timeline>
      <el-timeline v-else>
        <el-timeline-item v-for="e in filteredEvents" :key="`${e.type}-${e.data.id}`" :timestamp="e.date"
                          :type="e.type === 'shipment' ? 'info' : 'primary'" placement="top">
          <!-- 不可读时后端只返回本人写过/被派任务的记录（readable=false），这里照常渲染 -->
          <template v-if="e.type === 'shipment'">
            发货 {{ e.data.shipment_no }} · {{ e.data.quantity }} 件<span v-if="e.data.received_date">（{{ e.data.received_date }} 签收）</span>
          </template>
          <template v-else>
            <p class="tl-summary">{{ e.data.summary || e.data.raw_text }}</p>
            <ul class="tl-items">
              <li v-for="i in e.data.items" :key="i.id" :class="`kind-${i.kind}`">
                <StatusBadge v-if="i.kind !== 'content'" :value="i.kind" :dictionary="ITEM_KIND_STATUS" :label="i.category || undefined" size="small" />
                {{ i.text }}<span v-if="i.status === 'resolved'" class="resolved">已解决</span>
              </li>
            </ul>
            <p class="tl-meta">{{ e.data.author_name }} · {{ e.data.channel || '—' }}<span v-if="e.data.next_date"> · 下次 {{ e.data.next_date }}</span></p>
            <p v-if="e.data.result_code || e.data.obstacles?.length" class="tl-meta">{{ [e.data.result_code, ...(e.data.obstacles || [])].filter(Boolean).join(' · ') }}</p>
            <p v-if="e.data.created_at && !e.data.created_at.startsWith(e.date)" class="tl-meta">录入于 {{ formatBeijingDateTime(e.data.created_at) }}</p>
            <div v-if="e.data.attachments.length" class="tl-shots">
              <GlassButton v-for="a in e.data.attachments" :key="a.id" variant="link" @click="preview(a)">截图 {{ a.seq }}</GlassButton>
            </div>
            <div class="tl-actions">
              <GlassButton v-if="mayEditFollowup(auth.user, e.data)" v-permission="'domestic_followup:write'" variant="link" @click="recordAction('edit', e.data.id)">修改</GlassButton>
              <GlassButton variant="link" @click="recordAction('history', e.data.id)">修改历史</GlassButton>
            </div>
          </template>
        </el-timeline-item>
      </el-timeline>
      <el-empty v-if="!moreLoading && (eventType === 'collaboration' ? !collaborationEvents.length : !filteredEvents.length)"
                :description="data || eventType === 'collaboration' ? '暂无此类记录' : '当前范围仅提供客户摘要'" />
      <GlassButton v-if="eventType === 'collaboration' ? collaborationEvents.length < collaborationEventTotal : eventPages[eventType]?.has_more"
                   variant="outline" :loading="moreLoading" @click="loadMore">加载更早历史</GlassButton>
    </div>
    <el-empty v-else-if="!loading" description="当前范围没有可查看的客户信息" />
    <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" teleported @close="closePreview" />
  </DetailDrawer>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError, msgSuccessText } from '@/utils/feedback'
import { ITEM_KIND_STATUS } from '../followupStatus'
import { useAuthStore } from '@/stores/auth'
import { mayEditFollowup } from '../followupEdit'
import { copyText } from '@/utils/clipboard'
import { formatBeijingDateTime } from '@/utils/datetime'
import { COLLABORATION_ACTION, COLLABORATION_STATUS, DEAL_SOURCE, DEVELOPMENT_STAGE, dealLabel, labelFor, regionLabel } from '../customerOverview'
import CollaborationPanel from './CollaborationPanel.vue'
import CustomerSummaryActions from './CustomerSummaryActions.vue'

const emit = defineEmits(['record', 'edit', 'history', 'changed'])
const auth = useAuthStore()
const visible = ref(false)
const data = ref(null)
const selected = ref(null), collaboration = ref(null), customerId = ref(null), loading = ref(false), moreLoading = ref(false)
const openTasks = ref([])
const collaborationPanel = ref(null)
const previewUrl = ref('')
const eventType = ref('all'), collaborationEvents = ref([]), collaborationEventTotal = ref(0)
const contactFields = [{ key: 'phone', label: '电话' }, { key: 'wechat', label: '微信号' }]
const HANDOFF_OUTCOME = { accepted: '已接受', rejected: '已拒绝', withdrawn: '已撤回', invalidated: '已失效' }
const assignee = computed(() => collaboration.value?.owner_name || selected.value?.assignee_name)
const eventPages = ref({})
const filteredEvents = computed(() => eventPages.value[eventType.value]?.events || [])
const shareableRecords = computed(() => [...new Map(
  ['all', 'followup'].flatMap(key => eventPages.value[key]?.events || [])
    .filter(event => event.type === 'followup' && event.data.shared_summary).map(event => [event.data.id, event.data]),
).values()])
let controller
let sequence = 0
let eventSequence = 0
let collaborationPage = 0
function recordAction(action, id) { close(); emit(action, id) }
function record(historical = false) {
  const customer = { ...selected.value, ...data.value?.customer, id: customerId.value, writable: true, responsibility_version: collaboration.value?.version }
  close()
  emit('record', customer, historical === true)
}

const isOverdue = computed(() => {
  const c = data.value?.customer
  return Boolean(c?.frequency_days && c.days_since_followup != null && c.days_since_followup > c.frequency_days)
})
const lastLabel = computed(() => {
  const c = data.value?.customer
  if (!c?.last_followup_date) return '从未'
  return `${c.days_since_followup} 天前`
})

function close() {
  sequence++
  controller?.abort()
  closePreview()
  visible.value = false
  data.value = null
  selected.value = null
  collaboration.value = null
  openTasks.value = []
  eventPages.value = {}
  loading.value = false
  moreLoading.value = false
}

async function open(id, row = null, action = null) {
  close()
  const run = sequence
  controller = new AbortController()
  const options = { signal: controller.signal }
  customerId.value = id
  visible.value = true
  loading.value = true
  selected.value = row
  eventType.value = 'all'
  collaborationEvents.value = []; collaborationEventTotal.value = 0; collaborationPage = 0
  const [timeline, details, summary] = await Promise.allSettled([
    followupApi.timeline(id, undefined, options),
    followupApi.collaboration(id, options),
    followupApi.customerSummary(id, options),
  ])
  if (run !== sequence) return
  if (timeline.status === 'fulfilled' && timeline.value) {
    data.value = timeline.value
    eventPages.value.all = timeline.value
  }
  if (details.status === 'fulfilled') collaboration.value = details.value
  selected.value = summary.status === 'fulfilled' ? summary.value : null
  if (data.value) loadTasks(id, run)
  loading.value = false
  if (!data.value && collaboration.value) {
    eventType.value = 'collaboration'
    loadEventsForType()
  } else if (timeline.status === 'rejected' && (!selected.value || timeline.reason?.response?.status !== 403)) {
    if (!row && !selected.value) close()
    msgError(apiError(timeline.reason, '时间线加载失败'), timeline.reason)
  }
  if (action && collaboration.value?.available_actions.includes(action)) {
    await nextTick()
    if (run === sequence) collaborationPanel.value?.open(action)
  }
}
async function loadTasks(id, run) {
  try {
    const result = await followupApi.tasks({ customer_id: id, scope: 'visible', due: 'all', page_size: 50 })
    if (run === sequence) openTasks.value = result.items
  } catch (error) {
    if (run === sequence) msgError(apiError(error, '未完成事项加载失败'), error)
  }
}

async function loadMore() {
  if (moreLoading.value) return
  const run = sequence
  const eventRun = ++eventSequence
  const id = customerId.value
  const type = eventType.value
  moreLoading.value = true
  try {
    if (type === 'collaboration') {
      const nextPage = collaborationPage + 1
      const result = await followupApi.collaborationEvents(id, { page: nextPage, page_size: 20 }, { signal: controller.signal })
      if (run !== sequence || eventRun !== eventSequence) return
      collaborationEvents.value.push(...result.items)
      collaborationEventTotal.value = result.total
      collaborationPage = nextPage
    } else {
      const previous = eventPages.value[type]
      const result = await followupApi.timeline(id, { event_type: type, offset: previous?.next_offset || 0 }, { signal: controller.signal })
      if (run !== sequence || eventRun !== eventSequence) return
      eventPages.value[type] = { ...result, events: [...(previous?.events || []), ...result.events] }
    }
  } catch (error) {
    if (run === sequence && eventRun === eventSequence) msgError(apiError(error, '历史加载失败'), error)
  } finally {
    if (run === sequence && eventRun === eventSequence) moreLoading.value = false
  }
}
function loadEventsForType() {
  eventSequence++
  moreLoading.value = false
  if (eventType.value === 'collaboration' ? !collaborationPage : !eventPages.value[eventType.value]) loadMore()
}
function collaborationUpdated() {
  const id = customerId.value
  emit('changed')
  open(id)
}
async function copy(value) {
  if (await copyText(value)) msgSuccessText('已复制联系方式')
  else msgError('复制失败，请手动选取')
}
async function preview(att) {
  const run = sequence
  try {
    const url = await followupApi.attachmentUrl(att.id)
    if (run === sequence) { closePreview(); previewUrl.value = url }
    else URL.revokeObjectURL(url)
  } catch (e) { if (run === sequence) msgError(apiError(e, '截图加载失败'), e) }
}

function closePreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

defineExpose({ open, close })
onBeforeUnmount(close)
</script>

<style scoped>
.tl-head { display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 0 0 12px; }
.tl-head dt { font-size: 12px; color: var(--text-secondary); }
.tl-head dd { margin: 2px 0 0; font-weight: 600; }
.tl-head dd.overdue { color: var(--color-warning-text); }
.tl-record { margin-bottom: 12px; }
.tl-summary { margin: 0 0 4px; font-weight: 600; }
.tl-items { margin: 0 0 4px; padding-left: 16px; }
.resolved { margin-left: 6px; font-size: 12px; color: var(--color-success); }
.tl-meta { margin: 0; font-size: 12px; color: var(--text-secondary); }
.tl-section { margin: 12px 0; }
.tl-section h3 { margin: 0 0 8px; }
.tl-filter { width: 180px; }
@media (max-width: 768px) { .tl-head { grid-template-columns: repeat(2, 1fr); } }
</style>
