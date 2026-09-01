<template>
  <div v-if="displayPhotos.length" class="photos-wall">
    <figure v-for="(photo, i) in displayPhotos" :key="photo.id" class="photo-cell">
      <el-image
        :src="photo.url" :preview-src-list="urls" :initial-index="i"
        preview-teleported fit="cover" class="photo-img"
      />
      <figcaption class="photo-caption">{{ photo.caption }}</figcaption>
    </figure>
  </div>
  <span v-else-if="photos?.length" class="photos-loading">照片加载中…</span>
  <span v-else class="photos-loading">没有上传照片</span>
</template>

<script setup>
/**
 * 验货照片墙。图片端点要鉴权，浏览器 <img src> 不带 token，
 * 所以统一取 blob 再转 object URL（同 domestic 参考图 DomesticImages）。
 *
 * 排序：整单照片（item_id 为空）在前，其余按明细顺序分组，组内按 sort。
 * 每张照片下标注对应产品名称，整单照片标「整单照片」。
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { fetchImageBlobUrl } from '@/api/shipping'

const props = defineProps({
  photos: { type: Array, default: () => [] },
  items: { type: Array, default: () => [] },
})

const displayPhotos = ref([])
const urls = ref([])
// 批次令牌：快速切换详情时旧批次可能后完成，直接覆盖会让 object URL 泄漏、
// 而且显示的是上一张验货单的图。过期批次一律就地回收。
let batch = 0
let alive = true

function revokeAll() {
  urls.value.forEach(url => URL.revokeObjectURL(url))
  urls.value = []
  displayPhotos.value = []
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
      caption: photo.item_id == null ? '整单照片' : (nameOf(photo.item_id) || '整单照片'),
    }))
}

watch(() => [props.photos, props.items], async () => {
  const mine = ++batch
  revokeAll()
  const ordered = orderedPhotos()
  if (!ordered.length) return

  const loaded = (await Promise.all(ordered.map(async photo => {
    try {
      return { ...photo, url: await fetchImageBlobUrl(photo.file_path) }
    } catch {
      return null
    }
  }))).filter(Boolean)

  if (mine !== batch || !alive) {
    loaded.forEach(photo => URL.revokeObjectURL(photo.url))
    return
  }
  displayPhotos.value = loaded
  urls.value = loaded.map(photo => photo.url)
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
