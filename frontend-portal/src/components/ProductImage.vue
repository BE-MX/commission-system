<script setup>
import { computed, ref, watch } from 'vue'
const props = defineProps({ url: String, alt: { type: String, default: '' } })
const failed = ref(false)
// API paths only: never turn untrusted display data into a remote image request.
const source = computed(() => /^\/api\/portal\/v1\/catalog\/[a-f0-9-]{36}\/image\?version=[1-9][0-9]*$/i.test(props.url || '') ? props.url : null)
watch(() => props.url, () => { failed.value = false })
</script>
<template><img v-if="source && !failed" class="product-photo" :src="source" :alt="alt" loading="lazy" decoding="async" referrerpolicy="no-referrer" @error="failed = true" /><div v-else class="product-monogram" aria-hidden="true">L<span>S</span></div></template>
<style scoped>.product-photo { width: 100%; height: 100%; object-fit: contain; position: absolute; inset: 0; background: var(--portal-white); }</style>
