<template>
  <button ref="trigger" class="photo-trigger" :class="{ compact }" type="button" aria-label="查看物流单照片" @click.stop="openViewer">
    <img v-if="!compact && rectified.url.value" :src="rectified.url.value" alt="物流单缩略图" />
    <span v-else>物流单照片</span>
  </button>
  <el-dialog v-model="open" title="物流单照片" append-to-body width="760px" style="max-width: 94vw" align-center destroy-on-close :show-close="false">
    <template #header="{ close, titleId, titleClass }">
      <div class="viewer-heading"><span :id="titleId" :class="titleClass">物流单照片</span><button type="button" @click="close">关闭</button></div>
    </template>
    <div class="viewport" @wheel.prevent="wheelZoom" @pointerdown="startPointer" @pointermove="movePointer"
      @pointerup="endPointer" @pointercancel="endPointer" @lostpointercapture="endPointer">
      <img v-if="shownUrl" :src="shownUrl" :alt="variant === 'original' ? '运单原图' : '增强裁正图'" draggable="false"
        :style="{ transform: `translate(${pan.x}px, ${pan.y}px) scale(${scale})` }" />
      <button v-else-if="failed" type="button" @click="retry++">照片加载失败，点击重试</button>
      <span v-else role="status">正在加载照片…</span>
    </div>
    <div class="controls">
      <div class="variants" role="group" aria-label="图片版本">
        <button type="button" :aria-pressed="variant === 'rectified'" @click="variant = 'rectified'">增强图</button>
        <button type="button" :aria-pressed="variant === 'original'" @click="variant = 'original'">原图</button>
      </div>
      <a v-if="shownUrl" :href="shownUrl" :download="`waybill-${photo.id}-${variant}.${extension}`">下载</a>
      <button v-if="scale > 1" type="button" @click="resetPosition">还原大小</button>
    </div>
    <p class="metadata">{{ [photo.created_by_name, formatBeijingDateTime(photo.created_at), sourceText[photo.number_source]].filter(Boolean).join(' · ') }}</p>
  </el-dialog>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { loadWaybillPhoto } from '@/api/waybillPhotos'
import { formatBeijingDateTime } from '@/utils/datetime'

const props = defineProps({ photo: { type: Object, required: true }, compact: Boolean })
const trigger = ref(null), visible = ref(false), open = ref(false), variant = ref('rectified'), retry = ref(0)
const sourceText = { barcode: '条码', ocr: 'AI 识别', manual: '手动' }
let observer
onMounted(() => {
  if (props.compact) return
  if (!window.IntersectionObserver) { visible.value = true; return }
  observer = new IntersectionObserver(([entry]) => { visible.value = entry.isIntersecting })
  observer.observe(trigger.value)
})
onBeforeUnmount(() => observer?.disconnect())

function useVariant(name, enabled) {
  const url = ref(''), failed = ref(false), mime = ref('')
  watch(() => [props.photo.id, props.photo.inspection_id, enabled.value, retry.value], async (_next, _prev, onCleanup) => {
    const controller = new AbortController()
    let objectUrl = ''
    onCleanup(() => { controller.abort(); if (objectUrl) URL.revokeObjectURL(objectUrl) })
    url.value = ''; failed.value = false
    if (!enabled.value) return
    try {
      const { data } = await loadWaybillPhoto(props.photo, name, controller.signal)
      if (controller.signal.aborted) return
      objectUrl = URL.createObjectURL(data)
      url.value = objectUrl; mime.value = data.type
    } catch {
      if (!controller.signal.aborted) failed.value = true
    }
  }, { immediate: true })
  return { url, failed, mime }
}
const rectified = useVariant('rectified', computed(() => visible.value || (open.value && variant.value === 'rectified')))
const original = useVariant('original', computed(() => open.value && variant.value === 'original'))
const selected = computed(() => variant.value === 'original' ? original : rectified)
const shownUrl = computed(() => selected.value.url.value)
const failed = computed(() => selected.value.failed.value)
const extension = computed(() => ({ 'image/png': 'png', 'image/webp': 'webp' }[selected.value.mime.value] || 'jpg'))
function openViewer() { variant.value = 'rectified'; open.value = true; if (rectified.failed.value) retry.value++ }

const scale = ref(1), pan = ref({ x: 0, y: 0 }), pointers = new Map()
function resetPosition() { scale.value = 1; pan.value = { x: 0, y: 0 }; pointers.clear() }
watch([variant, open, () => props.photo.id], resetPosition)

function transformAt(nextScale, anchor, nextAnchor, rect) {
  const factor = Math.min(8, Math.max(1, nextScale)) / scale.value
  const x = anchor.x - rect.left - rect.width / 2
  const y = anchor.y - rect.top - rect.height / 2
  scale.value *= factor
  const limit = (value, span) => Math.min(span * (scale.value - 1) / 2, Math.max(-span * (scale.value - 1) / 2, value))
  pan.value = {
    x: limit(x + nextAnchor.x - anchor.x + (pan.value.x - x) * factor, rect.width),
    y: limit(y + nextAnchor.y - anchor.y + (pan.value.y - y) * factor, rect.height),
  }
}
function point(event) { return { x: event.clientX, y: event.clientY } }
function wheelZoom(event) {
  transformAt(scale.value * (event.deltaY < 0 ? 1.2 : 1 / 1.2), point(event), point(event), event.currentTarget.getBoundingClientRect())
}
function startPointer(event) {
  if (!shownUrl.value || pointers.size >= 2) return
  event.currentTarget.setPointerCapture(event.pointerId)
  pointers.set(event.pointerId, point(event))
}
function gesture() {
  const [a, b] = pointers.values()
  return b ? { center: { x: (a.x+b.x)/2, y: (a.y+b.y)/2 }, distance: Math.hypot(b.x-a.x, b.y-a.y) }
    : { center: a, distance: 1 }
}
function movePointer(event) {
  if (!pointers.has(event.pointerId)) return
  const before = gesture()
  pointers.set(event.pointerId, point(event))
  const after = gesture()
  if (before.distance > 0) transformAt(scale.value * after.distance / before.distance, before.center, after.center, event.currentTarget.getBoundingClientRect())
}
function endPointer(event) { pointers.delete(event.pointerId) }
</script>

<style scoped>
.photo-trigger { display: inline-grid; place-items: center; width: 72px; height: 64px; padding: 0; overflow: hidden; border: 1px solid var(--el-border-color); border-radius: 6px; background: var(--el-fill-color-light); color: var(--color-primary-text); cursor: zoom-in; font: inherit; }
.photo-trigger img { width: 100%; height: 100%; object-fit: cover; }
.photo-trigger.compact { width: auto; min-height: 32px; height: auto; padding-inline: 6px; border: 0; background: transparent; }
.viewport { height: min(58dvh, 580px); position: relative; display: grid; place-items: center; overflow: hidden; touch-action: none; background: var(--el-fill-color-light); }
.viewport img { position: absolute; width: 100%; height: 100%; object-fit: contain; user-select: none; }
.controls { display: flex; flex-wrap: wrap; align-items: center; gap: 12px; margin-top: 8px; }
.controls a, .controls button, .viewer-heading button { display: inline-grid; place-items: center; min-height: 44px; min-width: 44px; color: var(--color-primary-text); }
.viewer-heading { display: flex; align-items: center; justify-content: space-between; }
.viewer-heading button { border: 0; background: transparent; cursor: pointer; }
.controls button { border: none; background: transparent; cursor: pointer; }
.metadata { color: var(--text-secondary); margin-bottom: 0; }
.variants { display: flex; border: 1px solid var(--el-border-color); border-radius: 6px; overflow: hidden; }
.variants button { min-width: 56px; }
.variants button[aria-pressed="true"] { background: var(--el-color-primary-light-9); font-weight: 600; }
</style>
