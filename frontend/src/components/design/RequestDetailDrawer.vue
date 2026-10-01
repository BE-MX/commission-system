<template>
  <DetailDrawer v-model="visible" title="预约详情" width="640px" direction="rtl" @close="$emit('update:modelValue', false)">
    <ListPageStatus :error="detailResource.errorMessage.value" :loading="detailResource.loading.value" :has-data="!!detail" @retry="detailResource.load()" />
    <ListPageStatus :error="dictsResource.errorMessage.value" :loading="dictsResource.loading.value" :has-data="!!dictsResource.data.value" @retry="loadDicts" />
    <template v-if="detail">
      <ResponsiveDescriptions :column="1" border size="small">
        <el-descriptions-item label="预约编号">{{ detail.request_no }}</el-descriptions-item>
        <el-descriptions-item label="业务员">{{ detail.salesperson_name }}</el-descriptions-item>
        <el-descriptions-item label="客户名称">{{ detail.customer_name }}</el-descriptions-item>
        <el-descriptions-item label="客户等级">{{ customerLevelLabel(detail.customer_level) }}</el-descriptions-item>
        <el-descriptions-item label="拍摄类型">{{ shootTypeLabel(detail.shoot_type) }}</el-descriptions-item>
        <el-descriptions-item v-if="detail.props_requirement" label="道具要求">{{ propsLabel(detail.props_requirement) }}</el-descriptions-item>
        <el-descriptions-item label="期望日期">
          {{ formatDatePeriod(detail.expect_start_date, detail.expect_start_period) }}
          ~
          {{ formatDatePeriod(detail.expect_end_date, detail.expect_end_period) }}
        </el-descriptions-item>
        <el-descriptions-item label="优先级">
          <StatusBadge :type="detail.priority === 'urgent' ? 'danger' : 'info'" size="small">
            {{ detail.priority === 'urgent' ? '加急' : '普通' }}
          </StatusBadge>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <StatusBadge :value="detail.status" :dictionary="REQUEST_STATUS" size="small" />
        </el-descriptions-item>
        <el-descriptions-item label="备注">{{ detail.remark || '-' }}</el-descriptions-item>
        <el-descriptions-item label="期望设计师">{{ preferredDesignerLabel }}</el-descriptions-item>
      </ResponsiveDescriptions>

      <!-- 附件列表 -->
      <div class="attachment-section">
        <h4>附件</h4>
        <ListPageStatus :error="attachmentsResource.errorMessage.value" :loading="attachmentsResource.loading.value" :has-data="attachments.length > 0" @retry="attachmentsResource.load()" />
        <div v-if="attachments.length" class="attachment-list">
          <div v-for="a in attachments" :key="a.id" class="attachment-item">
            <el-icon class="attachment-icon"><Paperclip /></el-icon>
            <span class="attachment-name" :title="a.file_name">{{ a.file_name }}</span>
            <span class="attachment-size">{{ formatFileSize(a.file_size) }}</span>
            <a @click.prevent="downloadAttachment(a)" href="javascript:void(0)" class="attachment-download">
              <el-icon><Download /></el-icon>
            </a>
          </div>
        </div>
        <el-empty v-else-if="!attachmentsResource.loading.value && !attachmentsResource.error.value" description="暂无附件" :image-size="40" />
      </div>

      <!-- 审批记录 -->
      <div class="timeline-section">
        <h4>审批记录</h4>
        <ListPageStatus :error="logsResource.errorMessage.value" :loading="logsResource.loading.value" :has-data="auditLogs.length > 0" @retry="logsResource.load()" />
        <el-timeline v-if="auditLogs.length">
          <el-timeline-item
            v-for="log in auditLogs"
            :key="log.id"
            :timestamp="log.created_at"
            placement="top"
            :type="timelineType(log.action)"
          >
            <p class="log-action">{{ LOG_ACTION_MAP[log.action] || log.action }}</p>
            <p class="log-operator">{{ log.operator_name }} ({{ ROLE_MAP[log.operator_role] || log.operator_role }})</p>
            <p class="log-transition" v-if="log.from_status || log.to_status">
              {{ STATUS_MAP[log.from_status] || log.from_status || '-' }} &rarr; {{ STATUS_MAP[log.to_status] || log.to_status || '-' }}
            </p>
            <p class="log-comment" v-if="log.comment">{{ log.comment }}</p>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else-if="!logsResource.loading.value && !logsResource.error.value" description="暂无审批记录" :image-size="60" />
      </div>
    </template>
  </DetailDrawer>
</template>

<script setup>
import { REQUEST_STATUS, REQUEST_STATUS_LABELS as STATUS_MAP, REQUEST_STATUS_TYPES as STATUS_TAG } from '@/views/design/designStatus.js'
import { ref, watch, computed } from 'vue'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { Paperclip, Download } from '@element-plus/icons-vue'
import { getRequestDetail, getAuditLogs, getAttachments, downloadAttachment, getDesigners } from '@/api/design'
import { getDictMap, buildDictLabel } from '@/utils/dict'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  requestId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue'])

const visible = ref(false)
const detailResource = useAsyncResource(async (id, { signal }) => id ? (await getRequestDetail(id, { signal, suppressToast: true })).data || null : null)
const attachmentsResource = useAsyncResource(async (id, { signal }) => id ? (await getAttachments(id, { signal, suppressToast: true })).data || [] : [])
const logsResource = useAsyncResource(async (id, { signal }) => id ? (await getAuditLogs(id, { signal, suppressToast: true })).data || [] : [])
const detail = detailResource.data
const attachments = computed(() => attachmentsResource.data.value || [])
const auditLogs = computed(() => logsResource.data.value || [])

const dictsResource = useAsyncResource(async (active, { signal }) => {
  if (!active) return null
  const [shootType, customerLevel, propsRequirement, designers] = await Promise.all([getDictMap('shoot_type'), getDictMap('customer_level'), getDictMap('props_requirement'), getDesigners({ signal, suppressToast: true })])
  return { shootType, customerLevel, propsRequirement, designers: designers.data || [] }
})
const shootTypeMap = computed(() => dictsResource.data.value?.shootType || {})
const customerLevelMap = computed(() => dictsResource.data.value?.customerLevel || {})
const propsMap = computed(() => dictsResource.data.value?.propsRequirement || {})
const designerList = computed(() => dictsResource.data.value?.designers || [])

const PERIOD_MAP = { am: '上午', pm: '下午' }


const LOG_ACTION_MAP = {
  submit: '提交申请',
  approve: '审批通过',
  reject: '驳回',
  confirm: '确认排期',
  start: '开始执行',
  complete: '完成',
  cancel: '取消',
  reschedule: '调整排期',
}
const ROLE_MAP = {
  salesperson: '业务员',
  supervisor: '主管',
  design_staff: '设计部',
}

function formatDatePeriod(d, period) {
  if (!d) return '-'
  return period ? `${d} ${PERIOD_MAP[period] || period}` : d
}

function shootTypeLabel(t) { return buildDictLabel(t, shootTypeMap.value) }

function propsLabel(t) {
  if (!t) return '-'
  return buildDictLabel(t, propsMap.value)
}

function customerLevelLabel(code) {
  if (!code) return '-'
  return customerLevelMap.value[code] || code
}

const preferredDesignerLabel = computed(() => {
  if (!detail.value) return '-'
  const id = detail.value.preferred_designer_id
  if (!id) return '随机分配'
  const d = designerList.value.find(d => d.id === id)
  return d ? d.name : `设计师#${id}`
})

function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

function timelineType(action) {
  const map = {
    submit: 'primary', approve: 'success', reject: 'danger',
    confirm: 'primary', start: 'warning', complete: 'success',
    cancel: 'info', reschedule: 'warning',
  }
  return map[action] || 'primary'
}

const loadDicts = () => dictsResource.load(true)
function loadDetail(requestId) {
  return Promise.all([detailResource.load(requestId, { clear: true }), attachmentsResource.load(requestId, { clear: true }), logsResource.load(requestId, { clear: true })])
}
watch([() => props.modelValue, () => props.requestId], ([opened, requestId]) => {
  visible.value = opened
  if (opened && requestId) { loadDicts(); loadDetail(requestId) }
  else { dictsResource.load(false, { clear: true }); loadDetail(null) }
}, { immediate: true })

watch(visible, (val) => {
  if (!val) emit('update:modelValue', false)
})
</script>

<style scoped>
.attachment-section {
  margin-top: 24px;
}
.attachment-section h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-primary);
}
.attachment-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.attachment-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--fill-color-lighter, #fafafa);
  border-radius: 6px;
  font-size: 13px;
}
.attachment-icon {
  color: var(--text-secondary);
  flex-shrink: 0;
}
.attachment-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.attachment-size {
  color: var(--text-secondary);
  font-size: 12px;
  flex-shrink: 0;
}
.attachment-download {
  color: var(--color-primary-text);
  flex-shrink: 0;
  cursor: pointer;
  display: flex;
  align-items: center;
}
.timeline-section {
  margin-top: 24px;
}
.timeline-section h4 {
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--text-primary);
}
.log-action {
  font-size: 13px;
  font-weight: 600;
  margin: 0 0 2px;
}
.log-operator {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0 0 2px;
}
.log-transition {
  font-size: 12px;
  color: var(--color-primary-text);
  margin: 0 0 2px;
}
.log-comment {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
}
</style>
