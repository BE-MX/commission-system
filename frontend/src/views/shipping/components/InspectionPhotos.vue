<template>
  <div v-if="displayPhotos.length" class="photos-wall">
    <figure v-for="photo in displayPhotos" :key="photo.id" class="photo-cell">
      <button v-if="photo.url" type="button" class="photo-preview-trigger" :aria-label="`预览：${photo.caption}`" @click="openPreview(photo)">
        <el-image :src="photo.url" :alt="photo.caption" fit="cover" class="photo-img" />
      </button>
      <div v-else class="photo-placeholder" role="status">
        <GlassButton v-if="photo.failed" variant="link" @click="retryPhoto(photo)">加载失败，重试</GlassButton>
        <span v-else>照片加载中…</span>
      </div>
      <figcaption class="photo-caption">{{ photo.caption }}{{ photo.stale ? ' · 旧版本证据，不作本次验货依据' : '' }}</figcaption>
      <GlassButton v-if="photo.url || photo.failed" variant="link" :loading="originalLoadingId === photo.id" @click="openOriginal(photo)">
        {{ originalLoadingId === photo.id ? '原图加载中' : photo.originalFailed ? '重试原图' : '查看原图' }}
      </GlassButton>
    </figure>
  </div>
  <span v-else class="photos-loading">没有上传照片</span>
  <el-image-viewer v-if="previewUrls.length" :url-list="previewUrls" :initial-index="previewIndex" teleported @close="previewUrls = []" />
  <el-image-viewer v-if="originalUrl" :url-list="[originalUrl]" teleported @close="closeOriginal" />
</template>

<script setup>
/**
 * 验货照片墙。图片端点要鉴权，浏览器 <img src> 不带 token，
 * 所以统一取 blob 再转 object URL（同 domestic 参考图 DomesticImages）。
 *
 * 排序：整单照片（item_id 为空）在前，其余按明细顺序分组，组内按 sort。
 * 每张照片下标注对应产品名称，整单照片标「整单照片」。
 */
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElImageViewer } from 'element-plus'
import GlassButton from '@/components/GlassButton.vue'
import { fetchImageBlobUrl, fetchImagePreviewBlobUrl } from '@/api/shipping'

const props = defineProps({
  photos: { type: Array, default: () => [] },
  items: { type: Array, default: () => [] },
})

const displayPhotos = ref([])
const urls = computed(() => displayPhotos.value.filter(photo => photo.url).map(photo => photo.url))
const previewUrls = ref([]), previewIndex = ref(0)
const originalUrl = ref(''), originalLoadingId = ref(null)
// 批次令牌：快速切换详情时旧批次可能后完成，直接覆盖会让 object URL 泄漏、
// 而且显示的是上一张验货单的图。过期批次一律就地回收。
let batch = 0
let alive = true
let controller = null, originalController = null

function openPreview(photo) {
  closeOriginal()
  // Freeze the gallery: an earlier photo finishing must not shift the current image.
  previewUrls.value = [...urls.value]
  previewIndex.value = previewUrls.value.indexOf(photo.url)
}

function closeOriginal() {
  originalController?.abort()
  originalController = null
  originalLoadingId.value = null
  if (originalUrl.value) URL.revokeObjectURL(originalUrl.value)
  originalUrl.value = ''
}

function revokeAll() {
  controller?.abort()
  closeOriginal()
  previewUrls.value = []
  urls.value.forEach(url => URL.revokeObjectURL(url))
  displayPhotos.value = []
}

async function loadPhoto(photo, mine, signal) {
  if (photo.loading || photo.url || signal.aborted) return
  photo.loading = true
  photo.failed = false
  try {
    const url = await fetchImagePreviewBlobUrl(photo.file_path, { signal })
    if (mine !== batch || !alive) URL.revokeObjectURL(url)
    else photo.url = url
  } catch {
    if (mine === batch && alive && !signal.aborted) photo.failed = true
  } finally { photo.loading = false }
}

function retryPhoto(photo) {
  return loadPhoto(photo, batch, controller.signal)
}

async function openOriginal(photo) {
  if (originalLoadingId.value === photo.id) return
  closeOriginal()
  previewUrls.value = []
  const mine = batch, request = new AbortController()
  originalController = request
  originalLoadingId.value = photo.id
  photo.originalFailed = false
  try {
    const url = await fetchImageBlobUrl(photo.file_path, { signal: request.signal, timeout: 300000, suppressToast: true, showLoading: false })
    if (mine !== batch || !alive || request.signal.aborted) URL.revokeObjectURL(url)
    else originalUrl.value = url
  } catch {
    if (mine === batch && alive && !request.signal.aborted) photo.originalFailed = true
  } finally {
    if (originalController === request) originalLoadingId.value = null
  }
}

function orderedPhotos() {
  const nameOf = id => props.items.find(item => item.item_id === id)?.product_name || ''
  const itemOrder = new Map(props.items.map((item, index) => [item.item_id, index]))
  return [...(props.photos || [])]
    .sort((a, b) => {
      const groupA = a.item_id == null ? -1 : (itemOrder.get(a.item_id) ?? 999)
      const groupB = b.item_id == null ? -1 : (itemOrder.get(b.item_id) ?? 999)
      return groupA - groupB || (a.sort ?? 0) - (b.sort ?? 0)
    })
    .map(photo => ({
      ...photo,
      caption: photo.item_id == null ? '整单照片' : (nameOf(photo.item_id) || '已删除明细'),
    }))
}

watch(() => [props.photos, props.items], () => {
  const mine = ++batch
  revokeAll()
  controller = new AbortController()
  const signal = controller.signal
  displayPhotos.value = orderedPhotos().map(photo => ({ ...photo, url: '', loading: false, failed: false, originalFailed: false }))
  const entries = displayPhotos.value
  let next = 0
  async function worker() {
    while (next < entries.length && mine === batch && alive) {
      await loadPhoto(entries[next++], mine, signal)
    }
  }
  // Do not flood the private media endpoint or wait for the slowest photograph.
  for (let i = 0; i < Math.min(3, entries.length); i++) worker()
}, { immediate: true, deep: true })

onBeforeUnmount(() => {
  alive = false
  revokeAll()
})
</script>

<style scoped>
.photos-wall {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.photo-cell {
  margin: 0;
  width: 108px;
}

.photo-img {
  width: 108px;
  height: 108px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  cursor: zoom-in;
}

.photo-placeholder { width: 108px; height: 108px; display: grid; place-items: center; border-radius: 8px; background: var(--toolbar-bg); color: var(--text-secondary); font-size: 12px; }
.photo-preview-trigger { display: block; border: 0; padding: 0; border-radius: 8px; background: transparent; cursor: zoom-in; }
.photo-preview-trigger:focus-visible { outline: 2px solid var(--color-primary); outline-offset: 3px; }

.photo-caption {
  margin-top: 4px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  text-align: center;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.photos-loading {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
