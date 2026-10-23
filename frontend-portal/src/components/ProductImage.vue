<script setup>
import { computed, ref, watch } from 'vue'
import { productImageSource } from '../state/productImage.mjs'
const props = defineProps({ url: String, size: String, eager: Boolean, alt: { type: String, default: '' } })
const failed = ref(false)
// API paths only: never turn untrusted display data into a remote image request.
const source = computed(() => productImageSource(props.url, props.size))
watch(source, () => { failed.value = false })
</script>
<template><img v-if="source && !failed" class="product-photo" :src="source" :alt="alt" :loading="eager ? 'eager' : 'lazy'" decoding="async" referrerpolicy="no-referrer" @error="failed = true" /><div v-else class="product-monogram" aria-hidden="true">L<span>S</span></div></template>
<style scoped>.product-photo { width: 100%; height: 100%; object-fit: contain; position: absolute; inset: 0; background: var(--portal-white); }</style>
