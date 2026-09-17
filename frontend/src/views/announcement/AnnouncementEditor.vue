<template>
  <section v-loading="loading" class="announcement-editor">
    <el-alert v-if="document?.status === 'withdrawn'" :title="document.withdrawal_reason" type="warning" :closable="false" />
    <template v-else-if="document">
      <el-form v-if="document.can_edit" label-position="top" class="meta-form" @change="dirty = true">
        <el-form-item label="公告类别" required>
          <el-select v-model="meta.category_id" placeholder="选择类别" @change="dirty = true">
            <el-option v-for="c in categories.filter(c => c.active)" :key="c.id" :label="c.title" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="生效时间（北京时间，可空）"><el-date-picker v-model="meta.effective_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" @change="dirty = true" /></el-form-item>
        <el-form-item label="截止时间（北京时间，可空）"><el-date-picker v-model="meta.expires_at" type="datetime" value-format="YYYY-MM-DDTHH:mm:ss" @change="dirty = true" /></el-form-item>
        <el-form-item label="重要公告"><el-switch v-model="meta.important" @change="dirty = true" /></el-form-item>
        <el-form-item label="更新说明"><el-input v-model="meta.change_note" maxlength="500" @input="dirty = true" /></el-form-item>
      </el-form>
      <div v-else class="read-meta">
        <el-tag>{{ document.category_name }}</el-tag><el-tag v-if="document.important" type="warning">重要</el-tag>
        <span>发布：{{ formatBeijingDateTime(document.published_at) }}</span>
        <span v-if="document.effective_at">生效：{{ formatBeijingDateTime(document.effective_at) }}</span>
        <span v-if="document.expires_at">截止：{{ formatBeijingDateTime(document.expires_at) }}</span>
      </div>
      <el-alert v-if="document.can_edit || document.pending_approval_id" :title="`审核通过后，完整图文将自动推送至「${config.group_name || '尚未配置公告群'}」`" type="info" :closable="false" />
      <KnowledgeEditor :key="`${document.id || 'new'}:${document.revision_id || 0}:${document.can_edit}`" ref="editor" :document="document" :role="document.can_edit ? 'editor' : 'viewer'" :saving="saving" external-controls @save="save" @dirty-change="editorDirty = $event" />
      <div class="actions">
        <el-button v-if="document.can_edit" v-any-permission="['announcement:write', 'announcement:admin']" :icon="Check" type="primary" :loading="saving" @click="editor.save()">保存草稿</el-button>
        <el-button v-if="document.can_edit && document.id" v-any-permission="['announcement:write', 'announcement:admin']" :icon="Promotion" :disabled="hasChanges || saving" @click="submit">提交审核</el-button>
        <el-button v-if="document.id && edit" :icon="View" :disabled="hasChanges" @click="preview">钉钉预览</el-button>
        <template v-if="edit && document.pending_approval_id && document.can_review">
          <el-button v-any-permission="['knowledge:review', 'announcement:admin']" :icon="Check" type="primary" :loading="saving" @click="review(true)">审核并发布</el-button>
          <el-button v-any-permission="['knowledge:review', 'announcement:admin']" :icon="Close" @click="review(false)">驳回</el-button>
        </template>
      </div>
    </template>
    <el-dialog v-model="previewOpen" title="钉钉图文预览（按顺序发送）" width="min(680px, 95vw)" append-to-body>
      <div v-for="(part, index) in parts" :key="index" class="message-part">
        <small>第 {{ index + 1 }} / {{ parts.length }} 条</small>
        <img v-if="part.kind === 'image'" :src="imageUrls[part.asset_id]" :alt="part.alt || '公告图片'" />
        <pre v-else>{{ part.text }}</pre>
      </div>
    </el-dialog>
  </section>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { ElMessageBox } from 'element-plus'
import { Check, Promotion, View, Close } from '@element-plus/icons-vue'
import KnowledgeEditor from '@/views/knowledge/components/KnowledgeEditor.vue'
import { announcementApi as api } from '@/api/announcement'
import { getKnowledgeImageBlob } from '@/api/knowledge'
import { formatBeijingDateTime } from '@/utils/datetime'
import { msgSuccess, msgError } from '@/utils/feedback'

const props = defineProps({ documentId: [Number, String], edit: Boolean, config: { type: Object, required: true }, categories: { type: Array, default: () => [] } })
const emit = defineEmits(['saved', 'dirty-change'])
const document = ref(null)
const editor = ref(null)
const loading = ref(false)
const saving = ref(false)
const dirty = ref(false)
const editorDirty = ref(false)
const meta = reactive({ category_id: null, important: false, effective_at: null, expires_at: null, change_note: '' })
const hasChanges = computed(() => dirty.value || editorDirty.value || !document.value?.id)
const previewOpen = ref(false)
const parts = ref([])
const imageUrls = reactive({})
watch(hasChanges, value => emit('dirty-change', value))

async function load(id = props.documentId) {
  loading.value = true
  try {
    document.value = id ? await api.get(`/${id}`, { edit: props.edit }) : {
      library_id: props.config.library_id, title: '', content_json: { type: 'doc', content: [{ type: 'paragraph' }] },
      can_edit: true, status: 'draft', version_no: 1,
    }
    for (const key of Object.keys(meta)) meta[key] = document.value[key] ?? ({ important: false, change_note: '' }[key] ?? null)
    dirty.value = false
    editorDirty.value = false
  } finally { loading.value = false }
}
async function save({ title, content, done, fail }) {
  if (!title.trim() || !meta.category_id) { fail(); return msgError('请填写标题并选择公告类别') }
  saving.value = true
  try {
    const payload = { ...meta, title, content, base_revision_id: document.value.revision_id }
    const result = document.value.id ? await api.put(`/${document.value.id}`, payload) : await api.post('', payload)
    done()
    await load(result.id)
    msgSuccess('保存')
    emit('saved')
  } catch { fail() } finally { saving.value = false }
}
async function submit() {
  if (hasChanges.value) return msgError('请先保存草稿')
  saving.value = true
  try { await api.post(`/${document.value.id}/submit`); await load(document.value.id); emit('saved'); msgSuccess('提交审核') }
  finally { saving.value = false }
}
async function review(approve) {
  let remark = ''
  try {
    if (!approve) remark = (await ElMessageBox.prompt('请填写驳回原因', '驳回公告', { inputPattern: /\S+/, inputErrorMessage: '原因不能为空' })).value
    else await ElMessageBox.confirm(`发布后将自动推送至「${props.config.group_name}」。`, '审核并发布', { confirmButtonText: '发布', cancelButtonText: '取消' })
  } catch { return }
  saving.value = true
  try { await api.post(`/${document.value.id}/review`, { approve, remark }); await load(document.value.id); emit('saved'); msgSuccess(approve ? '发布' : '驳回') }
  finally { saving.value = false }
}
async function preview() {
  parts.value = await api.get(`/${document.value.id}/preview`)
  for (const part of parts.value.filter(p => p.kind === 'image')) {
    if (!imageUrls[part.asset_id]) imageUrls[part.asset_id] = URL.createObjectURL((await getKnowledgeImageBlob(part.asset_id)).data)
  }
  previewOpen.value = true
}
onMounted(() => load())
onBeforeUnmount(() => Object.values(imageUrls).forEach(url => URL.revokeObjectURL(url)))
defineExpose({ hasChanges })
</script>

<style scoped>
.announcement-editor { display: grid; gap: 16px; }
.meta-form { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.read-meta, .actions { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }
.read-meta { color: var(--text-secondary); }
.message-part { padding: 16px; margin-bottom: 12px; border: 1px solid var(--border-color); border-radius: 10px; }
.message-part pre { white-space: pre-wrap; overflow-wrap: anywhere; font: inherit; }
.message-part img { display: block; max-width: 100%; margin-top: 12px; }
@media (max-width: 768px) { .meta-form { grid-template-columns: 1fr; } }
</style>
