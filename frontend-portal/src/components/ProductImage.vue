<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { productImageSource } from '../state/productImage.mjs'
import { queueImage } from '../state/imageQueue.mjs'
const props = defineProps({ url: String, size: String, eager: Boolean, alt: { type: String, default: '' } })
const failed = ref(false), loaded = ref(''), host = ref(null), visible = ref(false)
let observer, controller, generation = 0, mounted = false
// API paths only: never turn untrusted display data into a remote image request.
const source = computed(() => productImageSource(props.url, props.size))
function clear() {
  generation++; controller?.abort()
  if (loaded.value) URL.revokeObjectURL(loaded.value)
  loaded.value = ''; failed.value = false
}
async function load() {
  clear()
  if (!mounted || !source.value || (!visible.value && !props.eager)) return
  const current = generation, path = source.value
  controller = new AbortController()
  const signal = controller.signal
  try {
    const blob = await queueImage(async () => {
      // A bounded GET-only retry; never retry revoked access or missing assets.
      for (let attempt = 0; attempt < 2; attempt++) {
        const response = await fetch(path, { signal, credentials: 'same-origin', cache: 'no-store', redirect: 'error', referrerPolicy: 'no-referrer' })
        if (response.status === 503 && attempt === 0) {
          await response.body?.cancel()
          continue
        }
        if (!response.ok || !response.headers.get('content-type')?.startsWith('image/')) throw new Error('Image unavailable')
        return response.blob()
      }
    }, { signal, priority: props.eager ? 1 : 0 })
    if (current === generation && !signal.aborted && blob) loaded.value = URL.createObjectURL(blob)
  } catch { if (current === generation && !signal.aborted) failed.value = true }
}
watch([source, visible], load)
onMounted(() => {
  mounted = true
  if (props.eager || typeof IntersectionObserver === 'undefined') visible.value = true
  else {
    observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { visible.value = true; observer.disconnect() }
    }, { rootMargin: '120px' })
    observer.observe(host.value)
  }
})
onBeforeUnmount(() => { mounted = false; observer?.disconnect(); clear() })
</script>
<template><span ref="host" class="product-image-host"><img v-if="loaded && !failed" class="product-photo" :src="loaded" :data-source="source" :alt="alt" :loading="eager ? 'eager' : 'lazy'" decoding="async" referrerpolicy="no-referrer" @error="failed = true" /><span v-else class="product-monogram" aria-hidden="true">L<span>S</span></span></span></template>
<style scoped>.product-image-host { display: block; width: 100%; height: 100%; } .product-photo { width: 100%; height: 100%; object-fit: contain; position: absolute; inset: 0; background: var(--portal-white); }</style>
