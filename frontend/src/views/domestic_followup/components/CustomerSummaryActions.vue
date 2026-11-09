<template>
  <div class="customer-summary-actions">
    <GlassButton v-if="customer.can_edit_contact" v-permission="'domestic_followup:write'" variant="link" @click="open('contact')">补充资料</GlassButton>
    <GlassButton v-if="customer.can_verify_deal" v-permission="'domestic_followup:coordinate'" variant="link" @click="open('deal')">核实成交</GlassButton>
  </div>
  <el-dialog v-model="visible" :title="mode === 'contact' ? '补充客户资料' : '核实成交情况'" width="480px"
             append-to-body destroy-on-close :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving">
    <el-form label-position="top" @submit.prevent="save">
      <template v-if="mode === 'contact'">
        <el-form-item v-for="field in contactFields" :key="field.key" :label="field.label">
          <el-input v-model="form[field.key]" :maxlength="field.max" />
        </el-form-item>
      </template>
      <template v-else>
        <el-form-item label="核实结论" required>
          <el-select v-model="deal" aria-label="核实结论">
            <el-option v-for="value in ['won', 'unwon', 'unknown']" :key="value" :value="value" :label="DEAL_STATUS[value]" />
          </el-select>
        </el-form-item>
        <el-form-item label="核实依据" required>
          <el-input v-model="evidence" type="textarea" maxlength="500" />
        </el-form-item>
      </template>
    </el-form>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <ul v-if="matches.length"><li v-for="match in matches" :key="match.id">{{ [match.shop_name, match.province, match.city].filter(Boolean).join(' · ') }}</li></ul>
    <el-checkbox v-if="canConfirmDuplicate" v-model="confirmed">已核对疑似重复档案，确认资料属于当前客户</el-checkbox>
    <template #footer>
      <GlassButton :disabled="saving" @click="visible = false">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" :disabled="!canSave" @click="save">保存</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import GlassButton from '@/components/GlassButton.vue'
import { msgSuccessText } from '@/utils/feedback'
import { DEAL_STATUS } from '../customerOverview'

const props = defineProps({ customer: { type: Object, required: true } })
const emit = defineEmits(['updated'])
const contactFields = [
  { key: 'contact', label: '联系人', max: 60 }, { key: 'phone', label: '电话', max: 40 },
  { key: 'wechat', label: '微信号', max: 80 }, { key: 'province', label: '省份', max: 50 }, { key: 'city', label: '城市', max: 50 },
]
const visible = ref(false), mode = ref(''), saving = ref(false), error = ref('')
const form = reactive({})
const deal = ref('unknown'), evidence = ref('')
const matches = ref([]), confirmed = ref(false), canConfirmDuplicate = ref(false)
watch(form, resetDuplicate, { flush: 'sync' })
const changes = computed(() => Object.fromEntries(contactFields.filter(({ key }) => form[key]?.trim() !== (props.customer[key] || '')).map(({ key }) => [key, form[key]?.trim() || null])))
const canSave = computed(() => !saving.value && (mode.value === 'deal' ? Boolean(evidence.value.trim()) :
  Object.keys(changes.value).length && (!canConfirmDuplicate.value || confirmed.value)))
function resetDuplicate() {
  error.value = ''
  matches.value = []
  canConfirmDuplicate.value = false
  confirmed.value = false
}
function open(key) {
  mode.value = key
  for (const field of contactFields) form[field.key] = props.customer[field.key] || ''
  deal.value = props.customer.deal_status || 'unknown'
  evidence.value = ''
  resetDuplicate()
  visible.value = true
}
async function save() {
  if (!canSave.value) return
  saving.value = true
  error.value = ''
  try {
    if (mode.value === 'contact') await followupApi.updateCustomerContact(props.customer.id, { ...changes.value, duplicate_confirmed: confirmed.value })
    else await followupApi.verifyCustomerDeal(props.customer.id, { deal_status: deal.value, evidence: evidence.value.trim() })
    visible.value = false
    msgSuccessText(mode.value === 'contact' ? '已更新客户资料' : '已保存成交核实')
    emit('updated')
  } catch (failure) {
    const detail = apiError(failure, '保存失败')
    error.value = typeof detail === 'string' ? detail : detail.message || '请核对客户资料'
    matches.value = detail.matches || []
    canConfirmDuplicate.value = matches.value.length > 0
  } finally { saving.value = false }
}
</script>

<style scoped>
.customer-summary-actions { display: flex; gap: 12px; margin: 8px 0; flex-wrap: wrap; }
</style>
