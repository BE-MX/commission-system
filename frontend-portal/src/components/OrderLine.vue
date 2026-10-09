<script setup>
import { unitPrice, money } from '../presentation.mjs'
defineProps({ line: { type: Object, required: true }, showPrice: Boolean })
</script>
<template>
  <div class="order-line"><div><h3>{{ line.display_snapshot.model_name }}</h3><p class="small muted">{{ line.display_snapshot.color_name }}<span v-if="line.display_snapshot.customer_sku"> · {{ line.display_snapshot.customer_sku }}</span></p><p class="small"><span v-if="line.display_snapshot.length">Length: {{ line.display_snapshot.length }} · </span><span v-if="line.display_snapshot.weight">Weight: {{ line.display_snapshot.weight }} · </span>{{ line.quantity }} {{ line.display_snapshot.unit }}</p></div><div v-if="showPrice" class="order-line-price"><strong>{{ money(line.line_amount) }}</strong><small>{{ unitPrice(line.unit_price) }} / {{ line.display_snapshot.unit }}</small><small v-if="line.discount_amount && line.discount_amount !== '0.00'">Discount: {{ money(line.discount_amount) }}</small></div></div>
</template>
