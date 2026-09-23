<template>
  <div class="receipt-fields">
    <div class="fields-grid">
      <el-form-item label="本次回款金额" required><el-input-number v-model="form.amount" :precision="2" :min="0.01" :disabled="readonly" controls-position="right" /><span>{{ currency }}</span></el-form-item>
      <el-form-item label="回款日期" required><el-date-picker v-model="form.collection_date" value-format="YYYY-MM-DD" :disabled="readonly" /></el-form-item>
      <!-- hidePaymentType：下单抽屉里回款方式并入订单「付款方式」，不再单选小满回款方式 -->
      <el-form-item v-if="!hidePaymentType" label="回款方式" required><el-select v-model="form.payment_type" :loading="loading" :disabled="readonly" placeholder="选择小满回款方式"><el-option v-for="t in types" :key="t" :value="t" :label="t" /></el-select></el-form-item>
      <el-form-item v-if="showCharge" label="手续费"><el-input-number v-model="form.bank_charge" placeholder="留空为 0" :precision="2" :min="0" :disabled="readonly" controls-position="right" /></el-form-item>
    </div>
    <p v-if="!hidePaymentType && typesError" class="types-error" role="alert">回款方式加载失败。<el-button link type="primary" @click="loadTypes">重新加载</el-button></p>
    <el-form-item label="回款截图" required><ReceiptProofs v-model="form.attachment_ids" :readonly="readonly" @uploading="$emit('uploading', $event)" /></el-form-item>
    <el-form-item label="回款备注"><el-input v-model="form.remark" type="textarea" maxlength="500" :disabled="readonly" /></el-form-item>
  </div>
</template>
<script setup>
import { onMounted, ref } from 'vue'
import { getReceiptTypes } from '@/api/receipt'
import ReceiptProofs from './ReceiptProofs.vue'
const props = defineProps({ form: { type: Object, required: true }, currency: String, readonly: Boolean, showCharge: Boolean, hidePaymentType: Boolean })
defineEmits(['uploading'])
const types = ref([]), loading = ref(false), typesError = ref(false)
async function loadTypes() {
  loading.value = true; typesError.value = false
  try { types.value = await getReceiptTypes() }
  catch { typesError.value = true }
  finally { loading.value = false }
}
onMounted(() => { if (!props.hidePaymentType) loadTypes() })
</script>
<style scoped>
.fields-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:12px}.fields-grid :deep(.el-input-number),.fields-grid :deep(.el-date-editor){width:100%}.fields-grid span{font-size:12px;color:var(--text-secondary)}@media(max-width:768px){.fields-grid{grid-template-columns:1fr}}
</style>
