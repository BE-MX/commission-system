<template>
  <div class="deal-summary">
    <dt class="deal-heading">
      成交情况
      <GlassButton v-if="customer.can_edit_deal" v-any-permission="['domestic_followup:write', 'domestic_followup:coordinate']"
                   variant="link" aria-label="修改成交情况" @click="open">修改</GlassButton>
    </dt>
    <dd>{{ currentLabel }}</dd>
    <el-dialog v-model="visible" title="修改成交情况" width="480px" append-to-body destroy-on-close
               :show-close="!saving" :close-on-click-modal="!saving" :close-on-press-escape="!saving">
      <p class="deal-current">当前为{{ currentLabel }}</p>
      <el-form label-position="top" :disabled="saving" @submit.prevent="save">
        <el-form-item label="成交状态" required>
          <el-select v-model="status" aria-label="成交状态" placeholder="请选择成交状态">
            <el-option v-for="value in dealStatuses" :key="value" :value="value" :label="DEAL_STATUS[value]" />
            <el-option v-if="manual" value="automatic" label="恢复自动判定" />
          </el-select>
        </el-form-item>
        <el-form-item label="修改原因" required>
          <el-input v-model="reason" type="textarea" maxlength="500" aria-label="修改原因"
                    placeholder="填写核实依据或恢复原因" />
        </el-form-item>
      </el-form>
      <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon />
      <template #footer>
        <GlassButton :disabled="saving" @click="visible = false">取消</GlassButton>
        <GlassButton variant="primary" :loading="saving" :disabled="!canSave" @click="save">保存</GlassButton>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgSuccessText } from '@/utils/feedback'
import { DEAL_SOURCE, DEAL_STATUS, dealLabel, labelFor } from '../customerOverview'

const props = defineProps({ customer: { type: Object, required: true } })
const emit = defineEmits(['updated'])
const dealStatuses = ['won', 'unwon', 'unknown']
const visible = ref(false)
const status = ref('')
const reason = ref('')
const error = ref('')
const saving = ref(false)
const manual = computed(() => props.customer.deal_source === 'manual_override')
const currentLabel = computed(() => [
  dealLabel(props.customer),
  props.customer.deal_source && labelFor(DEAL_SOURCE, props.customer.deal_source),
].filter(Boolean).join(' · '))
const canSave = computed(() => !saving.value && status.value && reason.value.trim() &&
  (!manual.value || status.value !== props.customer.deal_status))

function open() {
  status.value = manual.value ? props.customer.deal_status : ''
  reason.value = ''
  error.value = ''
  visible.value = true
}

async function save() {
  if (!canSave.value) return
  const restoring = status.value === 'automatic'
  saving.value = true
  error.value = ''
  try {
    await followupApi.updateCustomerDeal(props.customer.id, {
      deal_status: restoring ? null : status.value,
      reason: reason.value.trim(),
    })
    visible.value = false
    msgSuccessText(restoring ? '已恢复自动判定' : '已修改成交情况')
    emit('updated')
  } catch (failure) {
    const detail = apiError(failure, '成交情况保存失败')
    error.value = typeof detail === 'string' ? detail : detail.message || '成交情况保存失败'
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.deal-heading { display: flex; align-items: center; flex-wrap: wrap; column-gap: 6px; color: var(--text-secondary); font-size: 12px; }
.deal-summary dd { margin: 2px 0 0; font-weight: 600; }
.deal-current { margin: 0 0 12px; color: var(--text-secondary); }
</style>
