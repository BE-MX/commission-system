<template>
  <div class="return-amounts">
    <div><span>货款冲减 · {{ currency }}</span><strong>{{ amount(value.reduction_amount) }}</strong></div>
    <div><span>现金退款 · {{ currency }}</span><strong>{{ amount(value.refund_amount) }}</strong></div>
    <div><span>未收货款减免 · {{ currency }}</span><strong>{{ amount(value.waived_amount) }}</strong></div>
  </div>
</template>
<script setup>
import { amount } from './returnState'
defineProps({ value: { type: Object, required: true }, currency: { type: String, default: '' } })
</script>
