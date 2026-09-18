<template>
  <div class="receipt-proofs">
    <AppUpload v-if="!readonly" :model-value="files" :upload-fn="upload" :show-list="false"
      accept="image/png,image/jpeg,image/webp" :max-size-mb="10" :limit="5" multiple transfer button-text="上传回款截图" />
    <p v-if="!readonly" class="help">PNG / JPG / WebP，每张不超过 10MB，最多 5 张。截图仅方舟留存。</p>
    <div class="proof-grid">
      <div v-for="file in files" :key="file.id" class="proof">
        <el-image v-if="file.url" :src="file.url" :alt="file.name || '回款截图'" :preview-src-list="urls" preview-teleported fit="contain" />
        <span v-else>凭证加载中</span>
        <small>{{ file.name || '回款截图' }}</small>
        <el-button v-if="!readonly" link type="danger" @click="remove(file.id)"><el-icon><Delete /></el-icon>移除</el-button>
      </div>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Delete } from '@element-plus/icons-vue'
import AppUpload from '@/components/AppUpload.vue'
import { getReceiptProof, uploadReceiptProof } from '@/api/receipt'

const props = defineProps({ modelValue: { type: Array, default: () => [] }, readonly: Boolean })
const emit = defineEmits(['update:modelValue', 'uploading'])
const files = ref([]), error = ref('')
const urls = computed(() => files.value.map(f => f.url).filter(Boolean))
let pending = 0, generation = 0, disposed = false
const ownedUrls = new Set()
function objectUrl(blob) { const url = URL.createObjectURL(blob); ownedUrls.add(url); return url }
watch(() => props.modelValue, async ids => {
  const current = ++generation
  files.value = ids.map(id => files.value.find(f => f.id === id) || { id })
  for (const file of files.value.filter(f => !f.url)) {
    try {
      const response = await getReceiptProof(file.id)
      if (disposed || generation !== current) return
      file.url = objectUrl(response.data)
    } catch { error.value = '部分凭证加载失败，请刷新后重试' }
  }
}, { immediate: true })
async function upload(file, onProgress) {
  pending += 1; emit('uploading', true); error.value = ''
  try {
    const row = await uploadReceiptProof(file, onProgress)
    if (disposed) return row
    files.value = [...files.value, { ...row, url: objectUrl(file) }]
    emit('update:modelValue', files.value.map(f => f.id))
    return row
  } finally { pending -= 1; emit('uploading', pending > 0) }
}
function remove(id) { files.value = files.value.filter(f => f.id !== id); emit('update:modelValue', files.value.map(f => f.id)) }
onBeforeUnmount(() => { disposed = true; generation += 1; ownedUrls.forEach(url => URL.revokeObjectURL(url)) })
</script>

<style scoped>
.proof-grid{display:flex;flex-wrap:wrap;gap:12px;margin-top:12px}.proof{display:flex;flex-direction:column;gap:6px;padding:8px;border:1px solid var(--border-color);border-radius:8px;width:126px}.proof .el-image{height:80px;width:108px}.proof small{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.help{font-size:12px;color:var(--text-secondary);line-height:1.7}.error{color:var(--color-danger-text)}
</style>
