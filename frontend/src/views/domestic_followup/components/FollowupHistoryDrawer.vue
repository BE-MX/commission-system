<template>
  <DetailDrawer v-model="visible" title="跟进修改记录" width="800px" :loading="loading">
    <ListPageStatus :error="error" :loading="loading" :has-data="false" :paged="false" @retry="open(recordId)">
      <el-empty v-if="!rows.length" description="这条跟进尚无修改记录" />
      <el-collapse v-else>
        <el-collapse-item v-for="revision in rows" :key="revision.id" :name="revision.id"
                          :title="`${formatBeijingDateTime(revision.created_at)} · ${revision.editor_name} · 版本 ${revision.version}`">
          <p class="history-reason">修改原因：{{ revision.reason }}</p>
          <div v-for="(change, index) in revisionChanges(revision)" :key="index" class="history-change">
            <strong>{{ change.label }}</strong>
            <div class="history-values"><section><span>修改前</span><p>{{ change.before }}</p></section>
              <section><span>修改后</span><p>{{ change.after }}</p></section></div>
          </div>
          <div v-for="side in ['before', 'after']" :key="side" class="history-shots">
            <span>{{ side === 'before' ? '原截图' : '修改后截图' }}：</span>
            <GlassButton v-for="attachment in revision[side].attachments || []" :key="attachment.id" variant="link"
                         @click="preview(attachment.id)">{{ attachment.file_name || `截图 ${attachment.seq}` }}</GlassButton>
          </div>
        </el-collapse-item>
      </el-collapse>
    </ListPageStatus>
    <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" teleported @close="closePreview" />
  </DetailDrawer>
</template>

<script setup>
import { onUnmounted, ref, watch } from 'vue'
import DetailDrawer from '@/components/DetailDrawer.vue'
import GlassButton from '@/components/GlassButton.vue'
import { followupApi, apiError } from '@/api/domesticFollowup'
import { msgError } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'
import { revisionChanges } from '../followupHistory'

const visible = ref(false), loading = ref(false), error = ref(''), rows = ref([]), previewUrl = ref('')
let recordId, generation = 0, previewGeneration = 0
async function open(id) {
  recordId = id
  const run = ++generation
  visible.value = loading.value = true
  rows.value = []
  error.value = ''
  try { const data = await followupApi.followupHistory(id); if (run === generation) rows.value = data }
  catch (failure) { if (run === generation) error.value = apiError(failure, '修改记录加载失败') }
  finally { if (run === generation) loading.value = false }
}
function closePreview() {
  previewGeneration++
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value)
  previewUrl.value = ''
}
async function preview(id) {
  closePreview()
  const run = previewGeneration
  try {
    const url = await followupApi.attachmentUrl(id)
    if (run === previewGeneration) previewUrl.value = url
    else URL.revokeObjectURL(url)
  } catch (failure) { if (run === previewGeneration) msgError(apiError(failure, '截图加载失败'), failure) }
}
watch(visible, value => { if (!value) { generation++; closePreview() } })
onUnmounted(() => { generation++; closePreview() })
defineExpose({ open })
</script>

<style scoped>
.history-reason { white-space: pre-wrap; overflow-wrap: anywhere; }
.history-change { padding: 12px 0; border-top: 1px solid var(--border-color); }
.history-values { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 8px; }
.history-values span, .history-shots { color: var(--text-secondary); }
.history-values p { white-space: pre-wrap; overflow-wrap: anywhere; margin: 4px 0; }
@media (max-width: 600px) { .history-values { grid-template-columns: 1fr; } }
</style>
