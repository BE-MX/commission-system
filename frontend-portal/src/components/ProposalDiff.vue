<script setup>
import { fieldLabel, fieldValue } from '../orderPresentation.mjs'
import OrderLine from './OrderLine.vue'
defineProps({ changes: { type: Object, default: null } })
</script>
<template>
  <details class="proposal-diff" open><summary>What changed</summary><p v-if="!changes" class="small muted">No earlier version is available. Review the full proposal below.</p><template v-else><p v-if="!changes.items?.length && !changes.fields?.length" class="small muted">No product or commercial changes from the previous version.</p><article v-for="line in changes.items" :key="line.line_key" class="diff-row"><h3>{{ ({ added: 'Product added', removed: 'Product removed', changed: 'Product updated' })[line.change] }}</h3><div class="diff-columns"><section><p class="eyebrow">PREVIOUS</p><OrderLine v-if="line.before" :line="line.before" show-price /><p v-else>Not included</p></section><section><p class="eyebrow gold">PROPOSED</p><OrderLine v-if="line.after" :line="line.after" show-price /><p v-else>Removed</p></section></div></article><article v-for="field in changes.fields" :key="field.field" class="diff-row"><h3>{{ fieldLabel(field.field) }}</h3><div class="diff-columns"><section><p class="eyebrow">PREVIOUS</p><p class="diff-value">{{ fieldValue(field.field, field.before) }}</p></section><section><p class="eyebrow gold">PROPOSED</p><p class="diff-value">{{ fieldValue(field.field, field.after) }}</p></section></div></article></template></details>
</template>
