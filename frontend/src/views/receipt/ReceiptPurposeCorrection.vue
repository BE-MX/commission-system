<template>
  <GlassButton v-if="eligible" v-any-permission="['receipt:write','receipt:admin']" :disabled="disabled || busy" @click="open">更正预售收款用途</GlassButton>
  <el-dialog v-model="visible" title="更正预售收款用途" width="640px" append-to-body :close-on-click-modal="false" :close-on-press-escape="!busy" :show-close="!busy">
    <p>{{ receipt.currency }} {{ receipt.amount }} · {{ receipt.receipt_no }}</p>
    <p>预付货款从本批开始支付商品款和运费；定金仅最后一批抵扣。已被批次占用的款项需先处理原结算。</p>
    <el-form label-position="top">
      <el-form-item label="正确用途"><el-select v-model="purpose" :disabled="busy"><el-option value="presale_advance" label="预付货款" /><el-option value="presale_deposit" label="定金（最后一批抵扣）" /></el-select></el-form-item>
      <el-form-item label="更正依据"><el-input v-model="reason" type="textarea" :disabled="busy" maxlength="500" placeholder="填写客户付款用途的核对依据（至少10字）" /></el-form-item>
    </el-form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
    <template #footer><GlassButton :disabled="busy" @click="visible = false">取消</GlassButton><GlassButton variant="primary" :loading="busy" :disabled="disabled || purpose === receipt.purpose || reason.trim().length < 10" @click="save">保存更正</GlassButton></template>
  </el-dialog>
</template>
<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { updatePresalePurpose } from '@/api/receipt'
const props = defineProps({ receipt: { type: Object, required: true }, disabled: Boolean })
const emit = defineEmits(['updated', 'busy', 'open'])
const visible = ref(false), busy = ref(false), purpose = ref(''), reason = ref(''), error = ref('')
const eligible = computed(() => props.receipt.status === 'active' && props.receipt.sync_status === 'synced'
  && props.receipt.collect_status === 1 && props.receipt.xiaoman_receipt_id
  && ['presale_deposit','presale_advance'].includes(props.receipt.purpose))
let disposed = false
function open() { if (props.disabled || busy.value) return; purpose.value = props.receipt.purpose; reason.value = ''; error.value = ''; visible.value = true }
async function save() {
  if (props.disabled || busy.value || !eligible.value || purpose.value === props.receipt.purpose || reason.value.trim().length < 10) return
  const id = props.receipt.id, version = props.receipt.version
  busy.value = true; error.value = ''
  try {
    const row = await updatePresalePurpose(id, { version, purpose: purpose.value, reason: reason.value.trim() })
    if (!disposed && props.receipt.id === id) {
      visible.value = false; busy.value = false
      await nextTick()
      emit('updated', row)
    }
  } catch (e) { if (!disposed) error.value = e.response?.data?.detail || '更正结果未确认，请刷新原回款核对' }
  finally { busy.value = false }
}
watch(busy, value => emit('busy', value))
watch(visible, value => emit('open', value))
onBeforeUnmount(() => { disposed = true; emit('busy', false); emit('open', false) })
</script>
