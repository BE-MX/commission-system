<template>
  <el-drawer class="customer-hub-drawer" :model-value="modelValue" title="开发信逐封审核"
    size="min(760px, 100vw)" :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving"
    @update:model-value="$emit('update:modelValue', $event)">
    <div v-loading="loading" class="review-body">
      <el-alert v-if="loadError" type="error" title="草稿详情加载失败，请重新加载后再审核。" :closable="false" show-icon>
        <template #default><el-button link type="primary" @click="reload">重新加载</el-button></template>
      </el-alert>
      <template v-else-if="detail">
        <header class="review-header">
          <h2>{{ detail.customer_name || `客户 #${detail.customer_id}` }}</h2>
          <p>
            状态：<el-tag :type="draftStatusTagType(detail.status)">{{ draftStatusLabel(detail.status) }}</el-tag>
            · 关系目标：{{ relationshipGoalLabel(detail.relationship_goal) }}
            <template v-if="revision"> · 版本 #{{ revision.revision_no ?? '-' }}</template>
          </p>
        </header>

        <section class="review-section">
          <h3>收件人与发件账号</h3>
          <dl class="review-fields">
            <div><dt>收件人</dt><dd>{{ recipientName || '未提供' }}</dd></div>
            <div>
              <dt>收件邮箱</dt>
              <dd>
                {{ recipientEmail || '未提供' }}
                <el-tag v-if="verificationStatus" :type="verificationStatusTagType(verificationStatus)" size="small">
                  验证：{{ verificationStatusLabel(verificationStatus) }}
                </el-tag>
              </dd>
            </div>
          </dl>
          <el-form label-position="top" :disabled="saving">
            <el-form-item label="发件账号（停用或已暂停的邮箱不可选）">
              <el-select v-model="approveForm.mailbox_binding_id" placeholder="选择发件账号" :loading="mailboxesLoading">
                <el-option v-for="mailbox in mailboxes" :key="mailbox.id" :value="mailbox.id"
                  :disabled="!isMailboxSelectable(mailbox)" :label="mailboxOptionLabel(mailbox)" />
              </el-select>
            </el-form-item>
          </el-form>
        </section>

        <section class="review-section">
          <h3>语言与时区</h3>
          <dl class="review-fields">
            <div><dt>写作语言</dt><dd>{{ revision?.language_tag || '未提供' }}（{{ languageSourceLabel(revision?.language_source) }}）</dd></div>
            <div><dt>语言依据</dt><dd>{{ revision?.language_basis || '未提供' }}</dd></div>
            <div><dt>收件人时区</dt><dd>{{ revision?.recipient_timezone || '未提供' }}</dd></div>
          </dl>
        </section>

        <section class="review-section">
          <h3>发送时间</h3>
          <div class="schedule-row">
            <GlassButton variant="secondary" left-icon="AlarmClock" :loading="previewLoading" :disabled="saving" @click="runPreview">计算候选时间</GlassButton>
            <span v-if="!preview && !previewFailed" class="hint">按收件人时区与办公时间政策计算，不产生发送任务。</span>
          </div>
          <template v-if="preview">
            <dl class="review-fields">
              <div><dt>客户当地时间</dt><dd>{{ localTimeText || '未提供' }}<template v-if="preview.timezone">（{{ preview.timezone }}）</template></dd></div>
              <div><dt>北京时间</dt><dd>{{ beijingTimeText || '未提供' }}</dd></div>
              <div><dt>UTC</dt><dd>{{ preview.scheduled_at_utc || '未提供' }}</dd></div>
            </dl>
            <ul v-if="preview.skipped_reasons?.length" class="skipped-list">
              <li v-for="(reason, index) in preview.skipped_reasons" :key="index">{{ reason }}</li>
            </ul>
          </template>
          <template v-else-if="previewFailed">
            <el-alert type="warning" title="排程服务不可用或无法计算候选时间：可手动选择北京时间，提交后由服务端复核。" :closable="false" show-icon />
            <el-form label-position="top" :disabled="saving" class="manual-schedule">
              <el-form-item label="手动选择发送时间（北京时间）">
                <el-date-picker v-model="manualBeijing" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" placeholder="选择北京时间" />
              </el-form-item>
            </el-form>
          </template>
        </section>

        <section class="review-section">
          <h3>主题与正文</h3>
          <el-alert v-if="dirty" type="info" title="内容已修改：保存后将生成新版本，已有审批自动失效。" :closable="false" show-icon class="section-alert" />
          <el-form label-position="top" :disabled="saving">
            <el-form-item label="主题"><el-input v-model="editForm.subject" maxlength="200" /></el-form-item>
            <el-form-item label="正文（纯文本）"><el-input v-model="editForm.body_text" type="textarea" :rows="12" /></el-form-item>
          </el-form>
        </section>

        <section class="review-section">
          <h3>中文释义（供审核，不发送）</h3>
          <p class="readonly-block">{{ revision?.meaning_summary_zh || '未提供' }}</p>
          <p v-if="revision?.angle || revision?.cta" class="hint">切入点：{{ revision?.angle || '未提供' }} · CTA：{{ revision?.cta || '未提供' }}</p>
        </section>

        <section class="review-section">
          <h3>证据账本</h3>
          <el-table v-if="claims.length" :data="claims" border class="list-table">
            <el-table-column prop="claim" label="主张" min-width="220" show-overflow-tooltip />
            <el-table-column label="来源 fact_id" min-width="110">
              <template #default="{ row }">{{ row.fact_id ?? '无来源（高风险）' }}</template>
            </el-table-column>
            <el-table-column prop="allowed_wording" label="允许措辞" min-width="200" show-overflow-tooltip />
          </el-table>
          <p v-else class="hint">该版本未引用证据事实。</p>
        </section>

        <section v-if="riskFlags.length" class="review-section">
          <el-alert type="warning" title="风险标记（批准前请逐条确认）" :closable="false" show-icon>
            <ul class="risk-list">
              <li v-for="(flag, index) in riskFlags" :key="index">{{ riskFlagText(flag) }}</li>
            </ul>
          </el-alert>
        </section>

        <section class="review-section">
          <el-form label-position="top" :disabled="saving">
            <el-form-item label="审批理由（可选，会随审批记录保存）">
              <el-input v-model="approveForm.reason" type="textarea" :rows="2" placeholder="如：证据已逐条核对，收件人为采购决策人" />
            </el-form-item>
          </el-form>
          <el-alert v-if="saveError" type="error" title="操作失败，填写内容已保留。如草稿已被他人修改，请重新加载后再操作。" :closable="false" show-icon>
            <template #default><el-button link type="primary" :disabled="saving" @click="reload">重新加载</el-button></template>
          </el-alert>
        </section>
      </template>
    </div>
    <template #footer>
      <GlassButton variant="ghost" :disabled="saving" @click="$emit('update:modelValue', false)">关闭</GlassButton>
      <GlassButton v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="secondary" left-icon="DocumentChecked"
        :loading="saving" :disabled="!dirty || saving || detail?.status !== 'draft'" @click="saveRevision">保存草稿</GlassButton>
      <GlassButton v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="danger" left-icon="Close"
        :loading="saving" :disabled="saving || detail?.status !== 'draft'" @click="reject">拒绝</GlassButton>
      <GlassButton v-if="detail?.status === 'approved'" v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="warning" left-icon="RefreshLeft"
        :loading="saving" :disabled="saving" @click="revoke">撤销</GlassButton>
      <GlassButton v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="primary" left-icon="Promotion"
        :loading="saving" :disabled="!canApprove || saving" @click="approve">批准并排程</GlassButton>
    </template>
  </el-drawer>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import {
  getDraft, createRevision, previewSchedule, approveDraft, rejectDraft, revokeDraft, listMailboxes,
} from '@/api/mailOutreach'
import { formatBeijingDateTime, formatInTimeZone, parseApiDateTime } from '@/utils/datetime'
import { msgSuccess } from '@/utils/feedback'
import GlassButton from '@/components/GlassButton.vue'
import { createSearchJobIdempotencyKey } from '../customerHubController'
import {
  draftStatusLabel, draftStatusTagType, relationshipGoalLabel, languageSourceLabel,
  verificationStatusLabel, verificationStatusTagType, mailboxAuthStatusLabel, isMailboxSelectable,
} from '@/views/mail_outreach/presentation'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  draftId: { type: [Number, String], default: null },
})
const emit = defineEmits(['update:modelValue', 'updated'])

const detail = ref(null)
const loading = ref(false)
const loadError = ref(null)
const saving = ref(false)
const saveError = ref(null)
const requestKey = ref('')

const mailboxes = ref([])
const mailboxesLoading = ref(false)

const editForm = reactive({ subject: '', body_text: '' })
const approveForm = reactive({ mailbox_binding_id: null, reason: '' })
// 表单任何变动即重新生成幂等键（QualificationPanel 同范式）：重复提交去重，内容变更后视为新请求
watch([editForm, approveForm], () => { requestKey.value = createSearchJobIdempotencyKey() }, { flush: 'sync' })

const preview = ref(null)
const previewLoading = ref(false)
const previewFailed = ref(false)
const manualBeijing = ref('')

const revision = computed(() => detail.value?.revision || detail.value?.current_revision || null)
const claims = computed(() => Array.isArray(revision.value?.claims_json) ? revision.value.claims_json : [])
const riskFlags = computed(() => Array.isArray(revision.value?.risk_flags_json) ? revision.value.risk_flags_json : [])
const recipientName = computed(() => detail.value?.contact_name || detail.value?.recipient_name || '')
const recipientEmail = computed(() => detail.value?.to_email || detail.value?.recipient_email || detail.value?.email || '')
const verificationStatus = computed(() => detail.value?.verification_status || detail.value?.contact_point_verification_status || '')

const dirty = computed(() => !!revision.value && (
  editForm.subject !== (revision.value.subject || '') || editForm.body_text !== (revision.value.body_text || '')
))

const localTimeText = computed(() => {
  if (!preview.value) return ''
  const timeZone = preview.value.timezone || revision.value?.recipient_timezone
  return formatInTimeZone(preview.value.scheduled_at_utc, timeZone) || preview.value.scheduled_at_local || ''
})
const beijingTimeText = computed(() => preview.value?.scheduled_at_beijing
  ? formatBeijingDateTime(preview.value.scheduled_at_beijing, { seconds: false })
  : '')
const manualUtc = computed(() => parseApiDateTime(manualBeijing.value)?.toISOString() || '')
const scheduledAtUtc = computed(() => preview.value?.scheduled_at_utc || manualUtc.value)

const canApprove = computed(() => {
  if (!detail.value || detail.value.status !== 'draft') return false
  if (dirty.value || loading.value || loadError.value) return false
  if (!revision.value?.id || !revision.value?.content_sha256) return false
  if (!approveForm.mailbox_binding_id) return false
  return Boolean(scheduledAtUtc.value)
})

function mailboxOptionLabel(mailbox) {
  const parts = [mailbox.sender_email, mailbox.display_name || '未命名', mailboxAuthStatusLabel(mailbox.auth_status)]
  if (mailbox.pause_reason) parts.push('已暂停')
  if (mailbox.status === 'disabled') parts.push('已停用')
  return parts.join(' · ')
}

function riskFlagText(flag) {
  if (typeof flag === 'string') return flag
  if (flag && typeof flag === 'object') return flag.message || flag.flag || flag.kind || JSON.stringify(flag)
  return String(flag)
}

watch(() => [props.modelValue, props.draftId], ([visible, id]) => {
  if (visible && id) reload()
})

async function reload() {
  if (saving.value || !props.draftId) return
  loading.value = true
  loadError.value = null
  saveError.value = null
  requestKey.value = createSearchJobIdempotencyKey()
  try {
    const response = await getDraft(props.draftId)
    detail.value = response?.data || null
    const rev = detail.value?.revision || detail.value?.current_revision || {}
    editForm.subject = rev.subject || ''
    editForm.body_text = rev.body_text || ''
    approveForm.reason = ''
    preview.value = null
    previewFailed.value = false
    manualBeijing.value = ''
    loadMailboxes()
  } catch (error) {
    detail.value = null
    loadError.value = error
  } finally {
    loading.value = false
  }
}

async function loadMailboxes() {
  if (mailboxesLoading.value) return
  mailboxesLoading.value = true
  try {
    const response = await listMailboxes()
    const data = response?.data
    mailboxes.value = Array.isArray(data) ? data : (data?.items || [])
    const selectable = mailboxes.value.filter(isMailboxSelectable)
    if (!approveForm.mailbox_binding_id && selectable.length === 1) {
      approveForm.mailbox_binding_id = selectable[0].id
    }
  } catch {
    mailboxes.value = []
  } finally {
    mailboxesLoading.value = false
  }
}

async function runPreview() {
  if (previewLoading.value || saving.value) return
  previewLoading.value = true
  try {
    const response = await previewSchedule(props.draftId)
    preview.value = response?.data || null
    previewFailed.value = !preview.value?.scheduled_at_utc
    if (previewFailed.value) preview.value = null
  } catch {
    preview.value = null
    previewFailed.value = true
  } finally {
    previewLoading.value = false
  }
}

async function saveRevision() {
  if (!dirty.value || saving.value) return
  saving.value = true
  saveError.value = null
  try {
    await createRevision(props.draftId, { subject: editForm.subject.trim(), body_text: editForm.body_text })
    msgSuccess('草稿已保存为新版本')
    emit('updated')
    await reload()
  } catch (error) {
    saveError.value = error
  } finally {
    saving.value = false
  }
}

async function approve() {
  if (!canApprove.value || saving.value) return
  saving.value = true
  saveError.value = null
  try {
    await approveDraft(props.draftId, {
      revision_id: revision.value.id,
      mailbox_binding_id: approveForm.mailbox_binding_id,
      expected_content_sha256: revision.value.content_sha256,
      schedule_policy: revision.value.schedule_policy_json || {},
      scheduled_at_utc: scheduledAtUtc.value,
      reason: approveForm.reason.trim(),
      request_key: requestKey.value,
    })
    msgSuccess('已批准并排程')
    emit('updated')
    emit('update:modelValue', false)
  } catch (error) {
    saveError.value = error
  } finally {
    saving.value = false
  }
}

async function reject() {
  if (saving.value || !props.draftId) return
  let reason
  try {
    const result = await ElMessageBox.prompt('请填写拒绝理由（必填）。', '拒绝开发信', {
      confirmButtonText: '确定拒绝',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValidator: value => Boolean(value?.trim()) || '理由不能为空',
    })
    reason = result.value.trim()
  } catch { return }
  saving.value = true
  saveError.value = null
  try {
    await rejectDraft(props.draftId, { reason })
    msgSuccess('已拒绝')
    emit('updated')
    emit('update:modelValue', false)
  } catch (error) {
    saveError.value = error
  } finally {
    saving.value = false
  }
}

async function revoke() {
  if (saving.value || !props.draftId) return
  let reason
  try {
    const result = await ElMessageBox.prompt('请填写撤销理由（必填），未开始发送的任务将一并撤销。', '撤销已批准任务', {
      confirmButtonText: '确定撤销',
      cancelButtonText: '取消',
      inputType: 'textarea',
      inputValidator: value => Boolean(value?.trim()) || '理由不能为空',
    })
    reason = result.value.trim()
  } catch { return }
  saving.value = true
  saveError.value = null
  try {
    await revokeDraft(props.draftId, { reason })
    msgSuccess('已撤销')
    emit('updated')
    emit('update:modelValue', false)
  } catch (error) {
    saveError.value = error
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.review-body { min-height: 160px; }
.review-header h2 { margin: 0; font-size: 17px; color: var(--text-primary); }
.review-header p { margin: 6px 0 0; color: var(--text-secondary); }
.review-section { margin-top: 14px; padding: 14px; border: 1px solid var(--border-color); border-radius: 8px; }
.review-section h3 { margin: 0 0 10px; font-size: 14px; color: var(--text-primary); }
.review-fields { margin: 0; }
.review-fields > div { display: grid; grid-template-columns: minmax(96px, 28%) 1fr; gap: 14px; padding: 6px 0; border-bottom: 1px solid var(--border-color); }
.review-fields > div:last-child { border-bottom: 0; }
.review-fields dt { color: var(--text-muted); font-size: 13px; }
.review-fields dd { min-width: 0; margin: 0; color: var(--text-primary); font-weight: 500; overflow-wrap: anywhere; }
.schedule-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.manual-schedule { margin-top: 10px; }
.manual-schedule :deep(.el-date-editor) { width: 100%; }
.readonly-block { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; color: var(--text-secondary); line-height: 1.6; }
.hint { margin: 6px 0 0; color: var(--text-muted); font-size: 12px; }
.skipped-list { margin: 8px 0 0; padding-left: 20px; color: var(--text-secondary); font-size: 13px; }
.risk-list { margin: 6px 0 0; padding-left: 18px; }
.section-alert { margin-bottom: 10px; }
.review-section :deep(.el-select) { width: 100%; }
</style>
