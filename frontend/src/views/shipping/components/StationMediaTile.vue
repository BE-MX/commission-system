<template>
  <div ref="root" class="media-tile">
    <el-image v-if="url && media.media_type !== 'video'" :src="url" fit="cover" :preview-src-list="[url]" preview-teleported :alt="`验货照片 ${media.id}`" />
    <video v-else-if="url" :src="url" controls playsinline preload="metadata" />
    <button v-else type="button" class="media-load" :disabled="loading" @click="load">{{ loading ? '加载中…' : media.media_type === 'video' ? '▶ 点击预览视频' : '点击加载照片' }}</button>
    <span v-if="failed" role="status">加载失败，可重试</span>
    <small v-if="['pending', 'running'].includes(media.storage_state)" role="status">已在本地接收 · 等待云同步</small>
    <small v-else-if="media.storage_state === 'ready'">已同步到云端</small>
    <button v-if="editable" type="button" class="media-delete" :disabled="disabled" @click="$emit('remove', media)">删除{{ media.media_type === 'video' ? '视频' : '照片' }}</button>
  </div>
</template>
<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import { stationApi } from '@/api/shippingStation'
const props = defineProps({ media: Object, sessionId: String, editable: Boolean, disabled: Boolean })
const emit = defineEmits(['remove', 'error'])
const root = ref(null), url = ref(''), loading = ref(false), failed = ref(false)
let alive = true, observer
async function load() {
  if (loading.value || url.value) return
  loading.value = true; failed.value = false
  try {
    const result = await stationApi.media(props.sessionId, props.media.id)
    if (alive) url.value = URL.createObjectURL(result.data)
  } catch (e) { if (alive) { failed.value = true; emit('error', e) } }
  finally { loading.value = false }
}
onMounted(() => {
  if (props.media.media_type === 'video') return
  observer = new IntersectionObserver(entries => { if (entries.some(e => e.isIntersecting)) { load(); observer.disconnect() } })
  observer.observe(root.value)
})
onBeforeUnmount(() => { alive = false; observer?.disconnect(); if (url.value) URL.revokeObjectURL(url.value) })
</script>
<style scoped>
.media-tile{min-width:0;display:flex;flex-direction:column;gap:8px}.media-tile .el-image,.media-tile video{width:100%;height:140px;object-fit:cover;border-radius:12px;background:var(--page-bg)}.media-load{min-height:110px;border:1px dashed var(--border-hover);border-radius:12px;background:var(--page-bg);color:var(--text-secondary)}.media-delete{min-height:44px;border:1px solid var(--border-color);border-radius:10px;background:var(--card-bg);color:var(--color-danger)}.media-tile>span{font-size:12px;color:var(--color-danger)}
</style>
