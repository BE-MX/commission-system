<template>
  <section v-if="photos.length || error" aria-label="物流单照片" class="waybill-gallery">
    <h4>物流单照片</h4>
    <button v-if="error" type="button" @click="retry++">照片加载失败，点击重试</button>
    <div v-if="current.length" class="photo-list">
      <WaybillPhotoViewer v-for="photo in current" :key="photo.id" :photo="photo" />
    </div>
    <details v-if="replaced.length">
      <summary>历史照片（{{ replaced.length }}）</summary>
      <figure v-for="photo in replaced" :key="photo.id">
        <WaybillPhotoViewer :photo="photo" />
        <figcaption>已替换 · {{ formatBeijingDateTime(photo.replaced_at) }} · {{ photo.replaced_by_name || '—' }}</figcaption>
      </figure>
    </details>
  </section>
</template>
<script setup>
import { computed, ref, watch } from 'vue'
import { listWaybillPhotos } from '@/api/waybillPhotos'
import { formatBeijingDateTime } from '@/utils/datetime'
import WaybillPhotoViewer from './WaybillPhotoViewer.vue'

const props = defineProps({ inspectionId: Number, shipmentId: Number, version: Number })
const photos = ref([]), error = ref(false), retry = ref(0)
const current = computed(() => photos.value.filter(p => !p.replaced_at))
const replaced = computed(() => photos.value.filter(p => p.replaced_at))
watch(() => [props.inspectionId, props.shipmentId, props.version, retry.value], async (_value, _old, onCleanup) => {
  const controller = new AbortController()
  onCleanup(() => controller.abort())
  photos.value = []; error.value = false
  if (!props.inspectionId && !props.shipmentId) return
  try {
    const result = await listWaybillPhotos(props, { signal: controller.signal, suppressToast: true, showLoading: false })
    if (!controller.signal.aborted) photos.value = result.data
  } catch {
    if (!controller.signal.aborted) error.value = true
  }
}, { immediate: true })
</script>
<style scoped>
.waybill-gallery { margin-block: 12px; }
.waybill-gallery h4 { margin-block: 8px; }
.photo-list { display: flex; flex-wrap: wrap; gap: 8px; }
details { margin-top: 8px; }
summary { cursor: pointer; }
figure { display: inline-grid; gap: 4px; margin: 8px 12px 0 0; }
figcaption { color: var(--text-secondary); font-size: 12px; }
</style>
