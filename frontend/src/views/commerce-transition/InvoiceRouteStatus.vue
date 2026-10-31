<template>
  <div class="route-status" aria-label="订单正式来源及核对状态">
    <span>正式来源 <StatusBadge :type="invoiceIsLocal(invoice) ? 'success' : 'info'">{{ routeLabel(invoice.transaction_route || invoice.transaction_mode) }}</StatusBadge></span>
    <span>业务状态 <StatusBadge type="info">{{ businessLabel(invoice.commerce_status || invoice.status) }}</StatusBadge></span>
    <span>对比状态 <StatusBadge :type="invoice.shadow_status === 'consistent' ? 'success' : 'warning'">{{ shadowLabel(invoice.shadow_status) }}</StatusBadge></span>
    <span v-if="invoice.authority_epoch != null">办理权版本 {{ invoice.authority_epoch }}</span>
  </div>
</template>
<script setup>
import { routeLabel, businessLabel, shadowLabel, invoiceIsLocal } from './routeState'
defineProps({ invoice: { type: Object, required: true } })
</script>
<style scoped>.route-status { display: flex; align-items: center; flex-wrap: wrap; gap: 12px 20px; padding: 12px 0; color: var(--text-secondary); font-size: 13px; } .route-status > span { display: inline-flex; align-items: center; gap: 6px; }</style>
