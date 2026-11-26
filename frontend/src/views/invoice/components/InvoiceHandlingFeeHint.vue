<template>
  <div v-if="hint" class="handling-hint">
    <span>{{ hint }}</span>
    <el-button v-if="needsRecalculation" link type="primary" native-type="button" @click="onRecalculate">按费率重算</el-button>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { formatMoney } from '../../../utils/money.js'
import { computeHandlingFee, handlingFeeRate } from '../composables/invoiceSettlement'

const props = defineProps({
  form: { type: Object, required: true },
  total: { type: Number, required: true },
  onRecalculate: { type: Function, required: true },
})

const rate = computed(() => handlingFeeRate(props.form.internal_payment_method))
const expectedFee = computed(() => {
  if (rate.value == null) return null
  const base = Number(props.total || 0) - Number(props.form.surcharge_amount || 0)
  return computeHandlingFee(rate.value, base)
})
const needsRecalculation = computed(() => expectedFee.value != null
  && Math.abs(Number(props.form.surcharge_amount || 0) - expectedFee.value) > 0.005)
const hint = computed(() => {
  const method = props.form.internal_payment_method
  if (rate.value == null) return method && method.includes('报关') ? '报关：手动填写手续费' : ''
  const pct = `${(rate.value * 100).toFixed(0)}%`
  if (needsRecalculation.value) {
    return `与 ${pct}（应 ${formatMoney(expectedFee.value)}）不符`
  }
  return `${method} ${pct}（可手改）`
})
</script>

<style scoped>
.handling-hint { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 2px; color: var(--text-muted); font-size: 11px; line-height: 1.3; }
.handling-hint .el-button { margin-left: 0; font-size: 12px; }
</style>
