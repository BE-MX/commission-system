<template>
  <div v-if="attachments.length" class="attachment-links">
    <GlassButton v-for="attachment in attachments" :key="attachment.id" variant="link" @click="preview(attachment.id)">
      截图 {{ attachment.seq }}
    </GlassButton>
  </div>
  <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" teleported @close="closePreview" />
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'

const props = defineProps({ attachments: { type: Array, required: true } })
const previewUrl = ref('')
let previewRequest = 0

function closePreview() {
  previewRequest += 1
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}

async function preview(id) {
  closePreview()
  const request = previewRequest
  try {
    const url = await followupApi.attachmentUrl(id)
    if (request === previewRequest) previewUrl.value = url
    else URL.revokeObjectURL(url)
  } catch (error) {
    if (request === previewRequest) msgError(apiError(error, '截图加载失败'), error)
  }
}

watch(() => props.attachments, closePreview)
onBeforeUnmount(closePreview)
</script>

<style scoped>
.attachment-links { display: flex; flex-wrap: wrap; gap: 8px; }
</style>
