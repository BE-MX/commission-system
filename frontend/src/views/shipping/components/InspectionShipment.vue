<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { bindInspectionShipment } from '@/api/shipping'
const props = defineProps({ detail: { type: Object, required: true } })
const emit = defineEmits(['changed'])
let generation = 0, active = true
onBeforeUnmount(() => { active = false; generation++ })
const waybill = ref(''), carrier = ref(''), busy = ref(false), uncertain = ref(false), error = ref('')
watch(() => props.detail, value => { generation++; busy.value = false; uncertain.value = false; waybill.value = value.shipment?.waybill_no || ''; carrier.value = value.shipment?.carrier || ''; error.value = '' }, { immediate: true })
async function save() {
  if (busy.value || uncertain.value) return
  const id = props.detail.id, current = generation
  busy.value = true; error.value = ''
  try { await bindInspectionShipment(id, { waybill_no: waybill.value.trim(), carrier: carrier.value.trim(), edit_version: props.detail.edit_version, shipment_version: props.detail.shipment_version }); if (active && current === generation && props.detail.id === id) emit('changed', id) }
  catch (problem) { if (active && current === generation) { uncertain.value = !problem.response || problem.response.status >= 500; error.value = uncertain.value ? '结果未确认，请关闭后重新打开验货单核对关联结果。' : problem.response?.data?.detail || '保存失败，请核对后重试。' } }
  finally { if (active && current === generation) busy.value = false }
}
</script>
<template>
  <section aria-label="物流单" class="shipment-section">
    <h3>物流单</h3>
    <p v-if="detail.shipment">{{ detail.shipment.carrier }} · {{ detail.shipment.waybill_no }}</p>
    <form v-if="detail.status === 'submitted' && detail.can_bind_shipment" v-any-permission="['shipping_inspection:write', 'shipping_inspection:admin']" @submit.prevent="save">
      <p>先在物流跟踪上传并确认物流单，再将运单号与承运商关联到本验货单。<router-link v-permission="'tracking:write'" to="/tracking/upload">上传物流单</router-link></p>
      <label>运单号<el-input v-model="waybill" maxlength="50" :disabled="busy || uncertain" /></label>
      <label>承运商代码<el-input v-model="carrier" maxlength="30" :disabled="busy || uncertain" placeholder="与物流跟踪记录一致" /></label>
      <GlassButton native-type="submit" :loading="busy" :disabled="busy || uncertain || !waybill.trim() || !carrier.trim()">保存关联</GlassButton>
    </form>
    <el-alert v-if="error" :title="error" type="error" :closable="false" />
  </section>
</template>
<style scoped>
.shipment-section { margin-block: 20px; }
form { display: flex; flex-wrap: wrap; gap: 12px; align-items: end; }
form p { width: 100%; }
label { display: grid; gap: 6px; }
</style>
