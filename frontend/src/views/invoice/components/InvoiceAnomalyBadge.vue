<template>
  <span v-if="domains.length" class="invoice-anomaly" :title="domains.map(key => ANOMALY_LABELS[key]).join(' / ')">
    <span aria-hidden="true">!</span>
    <template v-for="(domain, index) in domains" :key="domain">
      <span v-if="index" aria-hidden="true">/</span>
      <button v-if="interactive" type="button" :aria-label="`查看${ANOMALY_LABELS[domain]}`" @click="$emit('navigate', domain)">{{ ANOMALY_LABELS[domain] }}</button>
      <span v-else>{{ ANOMALY_LABELS[domain] }}</span>
    </template>
  </span>
</template>
<script setup>
import { computed } from 'vue'
import { ANOMALY_LABELS } from '../composables/invoiceDetailState'
const props = defineProps({ anomalies: { type: Array, default: () => [] }, interactive: Boolean })
defineEmits(['navigate'])
const domains = computed(() => Object.keys(ANOMALY_LABELS).filter(key => props.anomalies.includes(key)))
</script>
<style scoped>
.invoice-anomaly{display:inline-flex;align-items:center;gap:4px;flex-wrap:wrap;border:1px solid var(--tag-danger-text);border-radius:5px;background:var(--tag-danger-bg);color:var(--tag-danger-text);padding:3px 6px;font-size:10px;font-weight:700;line-height:1.5;box-shadow:0 0 8px color-mix(in srgb,var(--tag-danger-text) 40%,transparent);vertical-align:super}
.invoice-anomaly button{border:0;background:none;color:inherit;font:inherit;padding:0;cursor:pointer;min-height:24px}
.invoice-anomaly button:focus-visible{outline:2px solid var(--tag-danger-text);outline-offset:2px}
@media(hover:none){.invoice-anomaly button{min-height:44px}}
</style>
