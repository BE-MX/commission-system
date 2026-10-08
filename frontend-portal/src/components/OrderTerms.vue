<script setup>
import { computed } from 'vue'
import { money } from '../presentation.mjs'
import { fieldLabel, fieldValue } from '../orderPresentation.mjs'
import OrderLine from './OrderLine.vue'
const props = defineProps({ document: { type: Object, required: true }, showPrice: Boolean })
const fees = computed(() => props.document.fees || props.document)
</script>
<template>
  <div class="order-terms"><OrderLine v-for="line in document.items" :key="line.line_key" :line="line" :show-price="showPrice" />
    <dl v-if="showPrice" class="quote-totals"><div><dt>Product subtotal</dt><dd>{{ money(document.product_amount) }}</dd></div><div><dt>Shipping</dt><dd>{{ money(fees.shipping_amount) }}</dd></div><div><dt>Packaging</dt><dd>{{ money(fees.packaging_amount) }}</dd></div><div><dt>{{ fees.surcharge_name || 'Additional charges' }}</dt><dd>{{ money(fees.surcharge_amount) }}</dd></div><div class="order-total"><dt>{{ document.total_amount == null ? 'Final total' : 'Total' }}</dt><dd>{{ money(document.total_amount) }}</dd></div></dl>
    <div class="order-detail-grid"><div><h3>Delivery details</h3><p>{{ fieldValue('delivery', document.delivery) }}</p></div><div><h3>Request details</h3><p v-if="document.customer_po">PO: {{ document.customer_po }}</p><p>{{ document.remark || 'No additional notes.' }}</p><template v-if="showPrice"><h3>Payment terms</h3><p>{{ fieldValue('payment_terms', document.payment_terms_snapshot || document.payment_terms) }}</p></template></div></div>
    <dl v-if="document.commercial_header" class="commercial-header"><template v-for="(value, key) in document.commercial_header" :key="key"><div v-if="value != null && value !== ''"><dt>{{ fieldLabel(key) }}</dt><dd>{{ fieldValue(key, value) }}</dd></div></template></dl>
  </div>
</template>
