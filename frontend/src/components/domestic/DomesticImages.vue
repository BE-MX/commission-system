<template>
  <div v-if="urls.length" class="dom-images">
    <el-image
      v-for="(url, i) in urls" :key="url"
      :src="url" :preview-src-list="urls" :initial-index="i"
      preview-teleported fit="cover" class="dom-image"
    />
  </div>
  <span v-else-if="paths?.length" class="dom-images-loading">图片加载中…</span>
</template>

<script setup>
/**
 * 内贸参考图展示。图片端点要鉴权，浏览器 <img src> 不带 token，
 * 所以统一取 blob 再转 object URL（同 aftersales 证据图）。
 */
import { onBeforeUnmount, ref, watch } from 'vue'
import { fetchImageBlobUrl } from '@/api/domestic'

const props = defineProps({
  paths: { type: Array, default: () => [] },
})

const urls = ref([])
// 批次令牌：快速切换详情时旧批次可能后完成，直接覆盖会让 object URL 泄漏、
// 而且显示的是上一条明细的图。过期批次一律就地回收。
let batch = 0
let alive = true

function revokeAll() {
  urls.value.forEach(url => URL.revokeObjectURL(url))
  urls.value = []
}

watch(() => props.paths, async paths => {
  const mine = ++batch
  revokeAll()
  if (!paths?.length) return

  const loaded = (await Promise.all(paths.map(async path => {
    try {
      return await fetchImageBlobUrl(path)
    } catch {
      return ''
    }
  }))).filter(Boolean)

  if (mine !== batch || !alive) {
    loaded.forEach(url => URL.revokeObjectURL(url))
    return
  }
  urls.value = loaded
}, { immediate: true, deep: true })

onBeforeUnmount(() => {
  alive = false
  revokeAll()
})
</script>

<style scoped>
.dom-images {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.dom-image {
  width: 84px;
  height: 84px;
  border-radius: 8px;
  border: 1px solid var(--el-border-color-lighter);
  cursor: zoom-in;
}

.dom-images-loading {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}
</style>
