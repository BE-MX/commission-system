<template>
  <el-dialog v-model="visible" title="快速建客户" width="480px" append-to-body destroy-on-close
             :close-on-click-modal="!saving" :close-on-press-escape="!saving" :show-close="!saving">
    <el-form label-position="top" @submit.prevent="save">
      <el-form-item label="店名" required><el-input v-model="form.shop_name" maxlength="120" /></el-form-item>
      <div class="prospect-fields">
        <el-form-item label="联系人"><el-input v-model="form.contact" maxlength="60" /></el-form-item>
        <el-form-item label="电话"><el-input v-model="form.phone" type="tel" maxlength="40" /></el-form-item>
        <el-form-item label="微信号"><el-input v-model="form.wechat" maxlength="80" /></el-form-item>
        <el-form-item label="省份"><el-input v-model="form.province" maxlength="50" /></el-form-item>
        <el-form-item label="城市"><el-input v-model="form.city" maxlength="50" /></el-form-item>
      </div>
    </el-form>
    <p v-if="!form.phone && !form.wechat" class="prospect-hint">联系方式未补齐，可以稍后补充。</p>
    <el-checkbox v-model="unwonConfirmed">已核实此前未成交</el-checkbox>
    <el-alert v-if="error" :title="error" type="warning" :closable="false" show-icon />
    <ul v-if="matches.length"><li v-for="match in matches" :key="match.id">
      <GlassButton variant="link" @click="reuse(match)">{{ [match.shop_name, match.province, match.city].filter(Boolean).join(' · ') }}</GlassButton>
    </li></ul>
    <el-checkbox v-if="canConfirmDuplicate" v-model="confirmed">我已核对，确认是不同的店</el-checkbox>
    <template #footer>
      <GlassButton :disabled="saving" @click="visible = false">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" :disabled="!form.shop_name.trim() || (canConfirmDuplicate && !confirmed)" @click="save">
        创建客户
      </GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import GlassButton from '@/components/GlassButton.vue'
import { msgSuccessText } from '@/utils/feedback'

const emit = defineEmits(['created', 'existing'])
const fields = { shop_name: '', contact: '', phone: '', wechat: '', province: '', city: '' }
const form = reactive({ ...fields })
const visible = ref(false), saving = ref(false), error = ref(''), canConfirmDuplicate = ref(false), confirmed = ref(false)
const unwonConfirmed = ref(false), matches = ref([])
watch(form, () => { error.value = ''; confirmed.value = false; canConfirmDuplicate.value = false; matches.value = [] }, { flush: 'sync' })

function open() {
  Object.assign(form, fields)
  error.value = ''; confirmed.value = false; canConfirmDuplicate.value = false
  unwonConfirmed.value = false
  matches.value = []
  visible.value = true
}
async function save() {
  if (saving.value || !form.shop_name.trim() || (canConfirmDuplicate.value && !confirmed.value)) return
  saving.value = true
  error.value = ''
  try {
    const payload = Object.fromEntries(Object.entries(form).map(([key, value]) => [key, value.trim() || null]))
    const customer = await followupApi.createProspect({ ...payload, duplicate_confirmed: confirmed.value, unwon_confirmed: unwonConfirmed.value })
    visible.value = false
    msgSuccessText('已创建客户')
    emit('created', customer)
  } catch (failure) {
    const detail = apiError(failure, '建档失败')
    error.value = typeof detail === 'string' ? detail : detail.message || '请核对客户资料'
    matches.value = detail.matches || []
    canConfirmDuplicate.value = Boolean(!detail.blocking && matches.value.length)
  } finally { saving.value = false }
}
function reuse(match) { visible.value = false; emit('existing', match) }
defineExpose({ open })
</script>

<style scoped>
.prospect-fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); column-gap: 12px; }
.prospect-hint { margin: 0 0 8px; color: var(--text-secondary); }
</style>
