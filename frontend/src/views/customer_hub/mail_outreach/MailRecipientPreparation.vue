<template>
  <section class="recipient-preparation">
    <div class="preparation-header">
      <h3>收件人准备</h3>
      <GlassButton variant="secondary" left-icon="Refresh" :loading="context.loading" @click="reload">刷新资料</GlassButton>
    </div>
    <el-alert v-if="context.error" type="error" title="收件资料加载失败，请刷新重试。" :closable="false" />
    <template v-else-if="context.data">
      <p class="hint">先核实邮箱、语言和时区，再生成草稿。公开页面上的邮箱不自动视为已验证或允许联系。</p>
      <div v-for="contact in context.data.contacts || []" :key="contact.contact_id" class="contact-row">
        <strong>{{ contact.display_name || contact.canonical_name }}</strong>
        <div v-for="point in contact.points || []" :key="point.contact_point_id">
          <span>{{ point.email }} · {{ point.eligible ? '可生成草稿' : '资料待补齐' }}</span>
          <p v-if="!point.eligible" class="hint">{{ (point.missing || []).map(missingLabel).join('；') }}</p>
          <GlassButton v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="link" left-icon="Edit" @click="editContact(contact, point)">补充 / 核实</GlassButton>
        </div>
      </div>
      <el-empty v-if="!context.data.contacts?.length" description="暂无联系人，请在下方补充已核实的收件资料。" :image-size="64" />
      <el-collapse v-model="expanded">
        <el-collapse-item title="添加或完善收件资料" name="edit">
          <el-form label-position="top" :disabled="saving" @submit.prevent="save">
            <el-form-item v-if="context.data.contact_candidates?.length" label="背调发现的联系人线索（仅填入，不代表已核实）">
              <el-select v-model="candidateId" clearable placeholder="选择线索或手动填写" @change="selectCandidate">
                <el-option v-for="candidate in context.data.contact_candidates" :key="candidate.fact_id" :value="candidate.fact_id" :label="candidateLabel(candidate)" />
              </el-select>
            </el-form-item>
            <div class="recipient-grid">
              <el-form-item label="联系人姓名"><el-input v-model="form.display_name" maxlength="128" /></el-form-item>
              <el-form-item label="收件邮箱"><el-input v-model="form.email" maxlength="255" placeholder="已确认归属的邮箱" /></el-form-item>
              <el-form-item label="写作语言"><el-input v-model="form.language_tag" placeholder="如 en、zh-CN、es" maxlength="32" /></el-form-item>
              <el-form-item label="收件人时区"><el-input v-model="form.timezone" placeholder="如 Asia/Shanghai、Europe/London" maxlength="64" /></el-form-item>
              <el-form-item label="国家代码（必填）"><el-input v-model="form.country_code" placeholder="如 CN、US" maxlength="2" /></el-form-item>
              <el-form-item label="来源链接"><el-input v-model="form.source_url" placeholder="可选，需与核实依据一致" maxlength="2048" /></el-form-item>
            </div>
            <el-form-item label="邮箱核实与可联系依据"><el-input v-model="form.verification_basis" type="textarea" :rows="3" placeholder="说明何时、通过何种方式确认邮箱归属及联系依据" maxlength="2000" /></el-form-item>
            <el-form-item><el-checkbox v-model="form.verified">我已核实该邮箱有效且属于目标联系人</el-checkbox></el-form-item>
            <el-form-item><el-checkbox v-model="form.contact_allowed">我已确认可联系依据，且没有退订或禁止联系记录</el-checkbox></el-form-item>
            <el-alert v-if="error" type="error" title="保存失败，资料已保留，请核对后重试。" :closable="false" />
            <GlassButton v-any-permission="['mail_outreach:write','mail_outreach:admin']" variant="primary" left-icon="Check" :loading="saving" :disabled="!canSave || saving" @click="save">保存收件资料</GlassButton>
          </el-form>
        </el-collapse-item>
      </el-collapse>
    </template>
  </section>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { getOutreachContext, saveRecipient } from '@/api/mailOutreach'
import { isEmail } from '@/utils/validators'
import { msgSuccess } from '@/utils/feedback'
import GlassButton from '@/components/GlassButton.vue'
import { createLatestResource } from '../customerHubResources'
import { RECIPIENT_MISSING_LABELS } from '@/views/mail_outreach/presentation'
const props = defineProps({ customerId: { type: [Number, String], required: true } })
const emit = defineEmits(['updated'])
const context = reactive(createLatestResource(getOutreachContext))
const saving = ref(false), error = ref(null), expanded = ref([]), candidateId = ref(null)
const blankForm = () => ({ display_name: '', email: '', language_tag: '', timezone: '', country_code: '', source_fact_id: null, source_url: '', verification_basis: '', verified: false, contact_allowed: false })
const form = reactive(blankForm())
const canSave = computed(() => Boolean(form.display_name.trim() && isEmail(form.email) && form.language_tag.trim() && form.timezone.trim() && form.country_code.trim().length === 2 && form.verification_basis.trim()))
const missingLabel = key => RECIPIENT_MISSING_LABELS[key] || key
const candidateLabel = candidate => [candidate.display_name, candidate.email].filter(Boolean).join(' · ') || JSON.stringify(candidate.value_json || {})
function reload() { return context.load(props.customerId) }
watch(() => props.customerId, () => { Object.assign(form, blankForm()); candidateId.value = null; expanded.value = []; reload() }, { immediate: true })
function editContact(contact, point) {
  Object.assign(form, blankForm(), { display_name: contact.display_name || contact.canonical_name || '', email: point.email || '', language_tag: contact.default_language || context.data.default_language || '', timezone: contact.timezone || context.data.timezone || '', country_code: contact.country_code || context.data.primary_country_code || '' })
  candidateId.value = null
  expanded.value = ['edit']
}
function selectCandidate(id) {
  const candidate = context.data?.contact_candidates?.find(item => item.fact_id === id)
  Object.assign(form, blankForm())
  if (!candidate) return
  const value = candidate.value_json || {}
  Object.assign(form, { display_name: candidate.display_name || value.display_name || value.name || '', email: candidate.email || value.email || '', language_tag: candidate.language_tag || '', timezone: candidate.timezone || '', country_code: candidate.country_code || '', source_fact_id: candidate.fact_id, source_url: candidate.source_url || '' })
}
async function save() {
  if (!canSave.value || saving.value) return
  saving.value = true; error.value = null
  try {
    await saveRecipient(props.customerId, { ...form, email: form.email.trim(), country_code: form.country_code.trim().toUpperCase(), source_url: form.source_url.trim() || null })
    msgSuccess('收件资料已保存，已重新检查触达资格')
    Object.assign(form, blankForm()); candidateId.value = null; expanded.value = []
    emit('updated')
    await reload()
  } catch (cause) { error.value = cause } finally { saving.value = false }
}
</script>

<style scoped>
.recipient-preparation { padding: 16px; border: 1px solid var(--border-color); border-radius: var(--card-radius); }
.preparation-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
h3 { margin: 0; font-size: 14px; }
.hint { color: var(--text-secondary); font-size: 13px; line-height: 1.6; }
.contact-row { padding: 10px 0; border-bottom: 1px solid var(--border-color); overflow-wrap: anywhere; }
.recipient-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
@media (max-width: 600px) { .recipient-grid { grid-template-columns: 1fr; } }
</style>
