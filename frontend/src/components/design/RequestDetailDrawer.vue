<template>
  <el-drawer v-model="visible" title="预约详情" size="480px" direction="rtl" @close="$emit('update:modelValue', false)">
    <template v-if="detail">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="预约编号">{{ detail.request_no }}</el-descriptions-item>
        <el-descriptions-item label="业务员">{{ detail.salesperson_name }}</el-descriptions-item>
        <el-descriptions-item label="客户名称">{{ detail.customer_name }}</el-descriptions-item>
        <el-descriptions-item label="客户等级">{{ customerLevelLabel(detail.customer_level) }}</el-descriptions-item>
        <el-descriptions-item label="拍摄类型">{{ shootTypeLabel(detail.shoot_type) }}</el-descriptions-item>
        <el-descriptions-item label="期望日期">
          {{ formatDatePeriod(detail.expect_start_date, detail.expect_start_period) }}
          ~
          {{ formatDatePeriod(detail.expect_end_date, detail.expect_end_period) }}
        </el-descriptions-item>
        <el-descriptions-item label="优先级">
          <el-tag :type="detail.priority === 'urgent' ? 'danger' : 'info'" size="small">
            {{ detail.priority === 'urgent' ? '加急' : '普通' }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="STATUS_TAG[detail.status]" size="small">
            {{ STATUS_MAP[detail.status] || detail.status }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="备注">{{ detail.remark || '-' }}</el-descriptions-item>
      </el-descriptions>

      <!-- 附件列表 -->
      <div class="attachment-section">
        <h4>附件</h4>
        <div v-if="attachments.length" class="attachment-list">
          <div v-for="a in attachments" :key="a.id" class="attachment-item">
            <el-icon class="attachment-icon"><Paperclip /></el-icon>
            <span class="attachment-name" :title="a.file_name">{{ a.file_name }}</span>
            <span class="attachment-size">{{ formatFileSize(a.file_size) }}</span>
            <a :href="getAttachmentDownloadUrl(a.id)" target="_blank" class="attachment-download">
              <el-icon><Download /></el-icon>
            </a>
          </div>
        </div>
        <el-empty v-else description="暂无附件" :image-size="40" />
      </div>

      <!-- 审批记录 -->
      <div class="timeline-section">
        <h4>审批记录</h4>
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
        <el-empty v-else description="暂无审批记录" :image-size="60" />
      </div>
    </template>
  </el-drawer>
</template>

<script setup>
import { ref, watch } from 'vue'
import { Paperclip, Download } from '@element-plus/icons-vue'
import { getRequestDetail, getAuditLogs, getAttachments, getAttachmentDownloadUrl } from '@/api/design'
import { getDictMap, buildDictLabel } from '@/utils/dict'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  requestId: { type: Number, default: null },
})

const emit = defineEmits(['update:modelValue'])

const visible = ref(false)
const detail = ref(null)
const attachments = ref([])
const auditLogs = ref([])

const shootTypeMap = ref({})
const customerLevelMap = ref({})

const PERIOD_MAP = { am: '上午', pm: '下午' }
const STATUS_MAP = {
  pending_audit: '待审批',
  pending_design: '待排期',
  scheduled: '已排期',
  in_progress: '进行中',
  completed: '已完成',
  rejected: '已拒绝',
  cancelled: '已取消',
}
const STATUS_TAG = {
  pending_audit: 'warning',
  pending_design: 'warning',
  scheduled: '',
  in_progress: '',
  completed: 'success',
  rejected: 'danger',
  cancelled: 'info',
}
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

function customerLevelLabel(code) {
  if (!code) return '-'
  return customerLevelMap.value[code] || code
}

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

async function loadDicts() {
  shootTypeMap.value = await getDictMap('shoot_type')
  customerLevelMap.value = await getDictMap('customer_level')
}

async function loadDetail(requestId) {
  detail.value = null
  attachments.value = []
  auditLogs.value = []
  if (!requestId) return

  try {
    const [detailRes, attRes, logRes] = await Promise.all([
      getRequestDetail(requestId),
      getAttachments(requestId),
      getAuditLogs(requestId),
    ])
    detail.value = detailRes.data || null
    attachments.value = attRes.data || []
    auditLogs.value = logRes.data || []
  } catch {
    detail.value = null
  }
}

watch(() => props.modelValue, (val) => {
  visible.value = val
  if (val && props.requestId) {
    loadDicts()
    loadDetail(props.requestId)
  }
})

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
  color: var(--color-primary);
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
  color: var(--color-primary);
  margin: 0 0 2px;
}
.log-comment {
  font-size: 12px;
  color: var(--text-secondary);
  margin: 0;
}
</style>
