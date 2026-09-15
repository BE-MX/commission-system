<template>
  <div class="video-list">
    <figure v-for="video in entries" :key="video.id" class="video-entry">
      <figcaption>{{ caption(video) }}</figcaption>
      <video v-if="video.url" :src="video.url" controls preload="metadata" />
      <GlassButton v-else variant="ghost" left-icon="VideoPlay" :loading="video.loading" @click="load(video)">
        {{ video.failed ? '重新加载视频' : '加载视频' }}
      </GlassButton>
    </figure>
  </div>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { fetchVideoBlobUrl } from '@/api/shipping'
import GlassButton from '@/components/GlassButton.vue'
const props = defineProps({ videos: { type: Array, default: () => [] }, items: { type: Array, default: () => [] } })
const entries = ref([])
let generation = 0
function clear() {
  generation++
  entries.value.forEach(video => { if (video.url) URL.revokeObjectURL(video.url) })
}
function caption(video) {
  return video.item_id == null ? '整单视频' : props.items.find(item => item.item_id === video.item_id)?.product_name || '明细视频'
}
async function load(video) {
  if (video.loading) return
  const current = generation
  video.loading = true
  try {
    const url = await fetchVideoBlobUrl(video.file_path)
    if (current !== generation) URL.revokeObjectURL(url)
    else video.url = url
  } catch { video.failed = true }
  finally { video.loading = false }
}
watch(() => props.videos, videos => { clear(); entries.value = (videos || []).map(video => ({ ...video, url: '', loading: false })) }, { immediate: true })
onBeforeUnmount(clear)
</script>

<style scoped>
.video-list { display: flex; flex-wrap: wrap; gap: 16px; }
.video-entry { margin: 0; width: 280px; }
figcaption { margin-bottom: 8px; font-size: 13px; overflow-wrap: anywhere; }
video { width: 100%; max-height: 220px; border-radius: 8px; background: var(--el-fill-color-light); }
</style>
