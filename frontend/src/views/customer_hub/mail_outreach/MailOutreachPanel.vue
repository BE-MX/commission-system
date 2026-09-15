<template>
  <section class="mail-outreach-panel" v-any-permission="['mail_outreach:read','mail_outreach:write','mail_outreach:admin']">
    <div class="panel-toolbar">
      <GlassButton v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="primary" left-icon="Plus" @click="openCreate">新建开发信</GlassButton>
      <GlassButton variant="secondary" left-icon="Refresh" :loading="draftsLoading" @click="refreshAll">刷新</GlassButton>
    </div>

    <h3 class="section-title">草稿与审批</h3>
    <el-alert v-if="draftsError" type="error" title="草稿列表加载失败，请重试。" :closable="false" show-icon />
    <div v-else class="table-card">
      <el-table v-loading="draftsLoading" :data="drafts" border class="list-table" row-key="id">
        <el-table-column label="状态" min-width="100">
          <template #default="{ row }"><el-tag :type="draftStatusTagType(row.status)">{{ draftStatusLabel(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="语言" min-width="90">
          <template #default="{ row }">{{ row.language_tag || row.revision?.language_tag || '-' }}</template>
        </el-table-column>
        <el-table-column label="收件邮箱" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ draftEmail(row) }}</template>
        </el-table-column>
        <el-table-column label="关系目标" min-width="100">
          <template #default="{ row }">{{ relationshipGoalLabel(row.relationship_goal) }}</template>
        </el-table-column>
        <el-table-column label="更新时间（北京时间）" min-width="160">
          <template #default="{ row }">{{ row.updated_at ? formatBeijingDateTime(row.updated_at, { seconds: false }) : '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="110" fixed="right">
          <template #default="{ row }"><GlassButton variant="link" left-icon="View" @click="openReview(row.id)">查看/审核</GlassButton></template>
        </el-table-column>
        <template #empty>该客户暂无开发信草稿，点击「新建开发信」生成。</template>
      </el-table>
    </div>
    <el-pagination v-model:current-page="draftsPage" :page-size="draftsPageSize" :total="draftsTotal"
      layout="total, prev, pager, next" @current-change="handleDraftsPageChange" />

    <h3 class="section-title">发送任务</h3>
    <el-alert v-if="jobsError" type="error" title="发送任务加载失败，请重试。" :closable="false" show-icon />
    <div v-else class="table-card">
      <el-table v-loading="jobsLoading" :data="jobs" border class="list-table" row-key="id">
        <el-table-column label="状态" min-width="130">
          <template #default="{ row }"><el-tag :type="jobStatusTagType(row.status)">{{ jobStatusLabel(row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="收件邮箱" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ row.to_email || row.to_email_snapshot || '-' }}</template>
        </el-table-column>
        <el-table-column label="计划发送时间（北京时间）" min-width="170">
          <template #default="{ row }">{{ row.due_at ? formatBeijingDateTime(row.due_at, { seconds: false }) : '-' }}</template>
        </el-table-column>
        <el-table-column label="顺延次数" min-width="90">
          <template #default="{ row }">{{ row.reschedule_count ?? 0 }}</template>
        </el-table-column>
        <template #empty>暂无发送任务；草稿批准并排程后会出现在这里。</template>
      </el-table>
    </div>
    <el-pagination v-model:current-page="jobsPage" :page-size="jobsPageSize" :total="jobsTotal"
      layout="total, prev, pager, next" @current-change="handleJobsPageChange" />

    <el-dialog v-model="createVisible" title="新建开发信" width="min(620px, calc(100vw - 32px))"
      :close-on-click-modal="!creating" :close-on-press-escape="!creating" :show-close="!creating">
      <div v-loading="context.loading" class="create-body">
        <el-alert v-if="context.error" type="error" title="触达上下文加载失败，请重试。" :closable="false" show-icon>
          <template #default><el-button link type="primary" @click="reloadContext">重试</el-button></template>
        </el-alert>
        <template v-else-if="context.data">
          <el-form label-position="top" :disabled="creating">
            <el-form-item label="联系人">
              <el-select v-model="createForm.contact_id" placeholder="选择联系人" @change="createForm.contact_point_id = null">
                <el-option v-for="contact in contacts" :key="contactKey(contact)" :value="contactKey(contact)" :label="contactLabel(contact)" />
              </el-select>
            </el-form-item>
            <el-form-item label="收件邮箱点">
              <el-select v-model="createForm.contact_point_id" placeholder="选择邮箱点" :disabled="!selectedContact">
                <el-option v-for="point in contactPoints" :key="pointKey(point)" :value="pointKey(point)"
                  :disabled="!point.eligible && !createForm.allowIneligible" :label="pointLabel(point)" />
              </el-select>
            </el-form-item>
            <el-alert v-if="selectedPoint && !selectedPoint.eligible" type="warning" :closable="false" show-icon
              title="该邮箱点暂不具备触达资格" class="missing-alert">
              <ul class="missing-list">
                <li v-for="(item, index) in missingItems(selectedPoint)" :key="index">{{ item }}</li>
              </ul>
            </el-alert>
            <el-form-item v-if="selectedPoint && !selectedPoint.eligible">
              <el-checkbox v-model="createForm.allowIneligible">我已知晓以上缺项，仅生成草稿查看（不具备资格不会排程发送）</el-checkbox>
            </el-form-item>
            <el-form-item label="关系目标">
              <el-radio-group v-model="createForm.relationship_goal">
                <el-radio-button v-for="option in RELATIONSHIP_GOAL_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </el-form>
          <el-alert v-if="createError" type="error" title="草稿生成失败，请重试。" :closable="false" show-icon />
        </template>
      </div>
      <template #footer>
        <GlassButton variant="ghost" :disabled="creating" @click="createVisible = false">取消</GlassButton>
        <GlassButton variant="primary" left-icon="MagicStick" :loading="creating" :disabled="!canCreate || creating" @click="submitCreate">生成草稿</GlassButton>
      </template>
    </el-dialog>

    <MailOutreachReviewDrawer v-model="reviewVisible" :draft-id="reviewDraftId" @updated="refreshAll" />
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { createDraft, getOutreachContext, listDrafts, listJobs } from '@/api/mailOutreach'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import GlassButton from '@/components/GlassButton.vue'
import { createLatestResource } from '../customerHubResources'
import { createSearchJobIdempotencyKey } from '../customerHubController'
import { useOperationsList } from '../composables/useOperationsList'
import MailOutreachReviewDrawer from './MailOutreachReviewDrawer.vue'
import {
  RELATIONSHIP_GOAL_OPTIONS, draftStatusLabel, draftStatusTagType, jobStatusLabel, jobStatusTagType,
  relationshipGoalLabel, verificationStatusLabel,
} from '@/views/mail_outreach/presentation'

const props = defineProps({
  customerId: { type: [Number, String], required: true },
})

const {
  loading: draftsLoading, list: drafts, total: draftsTotal, page: draftsPage, pageSize: draftsPageSize,
  error: draftsError, fetchList: fetchDrafts, handlePageChange: handleDraftsPageChange,
} = useOperationsList(params => listDrafts({ ...params, customer_id: props.customerId }))

const {
  loading: jobsLoading, list: jobs, total: jobsTotal, page: jobsPage, pageSize: jobsPageSize,
  error: jobsError, fetchList: fetchJobs, handlePageChange: handleJobsPageChange,
} = useOperationsList(params => listJobs({ ...params, customer_id: props.customerId }))

function refreshAll() {
  return Promise.all([fetchDrafts(), fetchJobs()])
}

function draftEmail(row) {
  return row.to_email || row.recipient_email || row.email || '-'
}

// ── 审核抽屉 ─────────────────────────────────────────────
const reviewVisible = ref(false)
const reviewDraftId = ref(null)
function openReview(draftId) {
  if (!draftId) return
  reviewDraftId.value = draftId
  reviewVisible.value = true
}

// ── 新建开发信 ───────────────────────────────────────────
const createVisible = ref(false)
const creating = ref(false)
const createError = ref(null)
const requestKey = ref('')
const context = reactive(createLatestResource(getOutreachContext))
const createForm = reactive({ contact_id: null, contact_point_id: null, relationship_goal: 'first_intro', allowIneligible: false })
watch(createForm, () => { requestKey.value = createSearchJobIdempotencyKey() }, { flush: 'sync' })

const contacts = computed(() => context.data?.contacts || [])
const selectedContact = computed(() => contacts.value.find(contact => contactKey(contact) === createForm.contact_id) || null)
const contactPoints = computed(() => {
  const contact = selectedContact.value
  if (!contact) return []
  return contact.email_points || contact.contact_points || contact.points || []
})
const selectedPoint = computed(() => contactPoints.value.find(point => pointKey(point) === createForm.contact_point_id) || null)

const canCreate = computed(() => {
  if (!createForm.contact_id || !createForm.contact_point_id || !createForm.relationship_goal) return false
  if (!selectedPoint.value) return false
  if (!selectedPoint.value.eligible && !createForm.allowIneligible) return false
  return true
})

function contactKey(contact) {
  return contact.contact_id ?? contact.id
}
function contactLabel(contact) {
  const name = contact.display_name || contact.canonical_name || contact.name || `联系人 #${contactKey(contact)}`
  const meta = [contact.job_title, contact.default_language, contact.timezone].filter(Boolean).join(' · ')
  return meta ? `${name}（${meta}）` : name
}
function pointKey(point) {
  return point.contact_point_id ?? point.id
}
function pointLabel(point) {
  const status = verificationStatusLabel(point.verification_status)
  const eligible = point.eligible ? '可触达' : '缺项'
  return `${point.email || pointKey(point)}（${status} · ${eligible}）`
}
function missingItems(point) {
  const missing = Array.isArray(point?.missing) ? point.missing : []
  return missing.map(item => (typeof item === 'string' ? item : item?.message || item?.code || JSON.stringify(item)))
}

function openCreate() {
  if (creating.value) return
  Object.assign(createForm, { contact_id: null, contact_point_id: null, relationship_goal: 'first_intro', allowIneligible: false })
  createError.value = null
  createVisible.value = true
  reloadContext()
}
function reloadContext() {
  return context.load(props.customerId)
}

async function submitCreate() {
  if (!canCreate.value || creating.value) return
  creating.value = true
  createError.value = null
  try {
    const response = await createDraft({
      customer_id: props.customerId,
      contact_id: createForm.contact_id,
      contact_point_id: createForm.contact_point_id,
      relationship_goal: createForm.relationship_goal,
      request_key: requestKey.value,
    })
    createVisible.value = false
    msgSuccess('草稿已生成')
    await fetchDrafts()
    const newId = response?.data?.id ?? response?.data?.draft_id
    if (newId) openReview(newId)
  } catch (error) {
    createError.value = error
  } finally {
    creating.value = false
  }
}
</script>

<style scoped>
.mail-outreach-panel { display: grid; gap: 12px; }
.panel-toolbar { display: flex; flex-wrap: wrap; gap: 10px; }
.section-title { margin: 6px 0 0; font-size: 14px; color: var(--text-primary); }
.create-body { min-height: 160px; }
.create-body :deep(.el-select) { width: 100%; }
.missing-alert { margin-bottom: 12px; }
.missing-list { margin: 6px 0 0; padding-left: 18px; }
.el-pagination { overflow-x: auto; }
</style>
