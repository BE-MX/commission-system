<template>
  <div class="media-workspace">
    <div class="media-aurora lg-aurora" aria-hidden="true">
      <div class="lg-aurora__blob lg-aurora__blob--gold" />
      <div class="lg-aurora__blob lg-aurora__blob--amber" />
      <div class="lg-aurora__blob lg-aurora__blob--peach" />
    </div>

    <header class="page-header">
      <div>
        <el-button link @click="router.back()"><el-icon><ArrowLeft /></el-icon> 返回设计管理</el-button>
        <h2>客户拍摄素材</h2>
        <p>{{ batch?.customer_name || '加载中' }} · 客户ID {{ batch?.customer_id || '-' }} · 任务 #{{ taskId }}</p>
      </div>
      <el-tag v-if="batch" :type="statusMeta.type" effect="plain">{{ statusMeta.label }}</el-tag>
    </header>

    <el-alert
      v-if="batch?.status === 'changes_requested'"
      :title="`审核退回：${batch.review_comment}`"
      type="warning"
      show-icon
      :closable="false"
      class="review-alert"
    />

    <section class="upload-panel lg-card">
      <div class="upload-entries">
        <div class="upload-drop" @drop.capture="onDropFolders">
          <el-upload
            drag
            multiple
            :auto-upload="false"
            :show-file-list="false"
            :disabled="!editable || uploading"
            accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm"
            :on-change="queueFile"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入图片、视频或文件夹，或点击选择文件</div>
            <template #tip>
              <div class="upload-tip">支持 JPG、PNG、WebP、GIF、MP4、MOV、WebM；可整体拖入文件夹（含多级目录），同名目录自动归入；原件上传，不做在线编辑。</div>
            </template>
          </el-upload>
        </div>
        <button type="button" class="portal-entry" :disabled="!batch" @click="showDirectoryDialog = true">
          <el-icon class="portal-entry-icon"><FolderOpened /></el-icon>
          <strong>客户素材门户</strong>
          <span>按目录管理 / 上传素材</span>
        </button>
      </div>
      <div v-if="uploadQueue.length" class="queue-list">
        <div v-for="item in uploadQueue" :key="item.uid" class="queue-item">
          <span>{{ item.name }}</span>
          <el-progress :percentage="item.progress" :status="item.error ? 'exception' : item.done ? 'success' : ''" />
        </div>
      </div>
    </section>

    <section class="asset-section">
      <div class="section-heading">
        <div><h3>本批素材</h3><span>{{ assets.length }} 个文件 · {{ totalSize }}</span></div>
        <GlassButton
          variant="warning"
          left-icon="Promotion"
          :disabled="!editable || !assets.length || uploading"
          :loading="submitting"
          @click="submitForReview"
        >完成拍摄并送审</GlassButton>
      </div>

      <div v-if="assets.length" class="asset-grid">
        <article v-for="asset in assets" :key="asset.id" class="asset-card lg-card">
          <img v-if="asset.media_type === 'image'" :src="asset.content_url" :alt="asset.file_name" @click="preview(asset)" />
          <video v-else :src="asset.content_url" controls preload="metadata" />
          <div class="asset-info">
            <strong :title="asset.file_name">{{ asset.file_name }}</strong>
            <span>{{ formatSize(asset.file_size) }}</span>
            <el-tag size="small" effect="plain" :type="asset.directory_id ? 'warning' : 'info'">{{ directoryLabel(asset) }}</el-tag>
          </div>
          <GlassButton v-if="editable" variant="link" link-tone="danger" left-icon="Delete" @click="removeAsset(asset)">删除</GlassButton>
        </article>
      </div>
      <el-empty v-else description="尚未上传素材" />
    </section>

    <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" @close="previewUrl = ''" />
    <CustomerMediaDirectoryDialog
      v-model="showDirectoryDialog"
      :batch="batch"
      :editable="editable"
      @update:batch="batch = $event"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, FolderOpened, UploadFilled } from '@element-plus/icons-vue'
import { deleteMediaAsset, getTaskMediaBatch, submitMediaBatch, uploadMediaAsset } from '@/api/customerMedia'
import CustomerMediaDirectoryDialog from './customer-media/CustomerMediaDirectoryDialog.vue'
import { collectDroppedFiles, dropHasDirectory } from './customer-media/droppedFiles'

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.taskId)
const batch = ref(null)
const uploading = ref(false)
const submitting = ref(false)
const uploadQueue = ref([])
const previewUrl = ref('')
const showDirectoryDialog = ref(false)

const assets = computed(() => batch.value?.assets || [])
const directories = computed(() => batch.value?.directories || [])
const editable = computed(() => ['draft', 'changes_requested'].includes(batch.value?.status))
const totalSize = computed(() => formatSize(assets.value.reduce((sum, item) => sum + item.file_size, 0)))
const statusMeta = computed(() => ({
  draft: { label: '上传中', type: 'info' },
  changes_requested: { label: '待修改', type: 'warning' },
  pending_review: { label: '待审核', type: 'warning' },
  published: { label: '已发布', type: 'success' },
  unpublished: { label: '已下架', type: 'info' },
}[batch.value?.status] || { label: batch.value?.status, type: 'info' }))

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

async function loadBatch() {
  const res = await getTaskMediaBatch(taskId)
  batch.value = res.data
}

function directoryLabel(asset) {
  if (!asset.directory_id) return '未分类'
  return directories.value.find(d => d.id === asset.directory_id)?.name || '未分类'
}

async function uploadOne(item, raw, options = {}) {
  try {
    const res = await uploadMediaAsset(batch.value.id, raw, event => {
      item.progress = event.total ? Math.round(event.loaded / event.total * 100) : 0
    }, options)
    item.progress = 100
    item.done = true
    batch.value = res.data
  } catch {
    item.error = true
  }
}

let queueSeq = 0
function pushQueueItem(name) {
  const item = { uid: `${Date.now()}-${queueSeq++}`, name, progress: 0, done: false, error: false }
  uploadQueue.value.push(item)
  return item
}

function scheduleQueueCleanup() {
  window.setTimeout(() => { uploadQueue.value = uploadQueue.value.filter(row => !row.done) }, 1200)
}

async function queueFile(uploadFile) {
  if (!editable.value) return
  uploading.value = true
  const item = pushQueueItem(uploadFile.name)
  await uploadOne(item, uploadFile.raw)
  uploading.value = uploadQueue.value.some(row => !row.done && !row.error)
  scheduleQueueCleanup()
}

const FOLDER_ACCEPT_RE = /\.(jpe?g|png|webp|gif|mp4|mov|webm)$/i

async function onDropFolders(e) {
  if (!editable.value || uploading.value) return
  if (!dropHasDirectory(e.dataTransfer)) return
  // 命中文件夹时拦截事件，自行递归遍历；纯文件仍交给 el-upload 处理
  e.preventDefault()
  e.stopPropagation()
  const { files } = await collectDroppedFiles(e.dataTransfer)
  const accepted = files.filter(({ file }) => FOLDER_ACCEPT_RE.test(file.name))
  const skipped = files.length - accepted.length
  if (skipped > 0) ElMessage.warning(`已忽略 ${skipped} 个不支持的文件（仅支持 JPG、PNG、WebP、GIF、MP4、MOV、WebM）`)
  if (!accepted.length) return
  uploading.value = true
  for (const { file, directoryName } of accepted) {
    // 顶层文件夹名作为目录名：后端按客户 find-or-create，同名目录直接归入不新建
    const item = pushQueueItem(directoryName ? `${directoryName}/${file.name}` : file.name)
    await uploadOne(item, file, directoryName ? { directoryName } : {})
  }
  uploading.value = uploadQueue.value.some(row => !row.done && !row.error)
  scheduleQueueCleanup()
}

async function removeAsset(asset) {
  try { await ElMessageBox.confirm(`删除 ${asset.file_name}？`, '删除素材', { type: 'warning' }) } catch { return }
  const res = await deleteMediaAsset(batch.value.id, asset.id)
  batch.value = res.data
  ElMessage.success('已删除')
}

async function submitForReview() {
  try {
    await ElMessageBox.confirm('提交后将完成拍摄任务并进入预约发起人的审核队列。', '完成并送审', { type: 'info' })
  } catch { return }
  submitting.value = true
  try {
    const res = await submitMediaBatch(batch.value.id, batch.value.lock_version)
    batch.value = res.data
    ElMessage.success('已送审')
  } finally { submitting.value = false }
}

function preview(asset) { previewUrl.value = asset.content_url }
onMounted(loadBatch)
</script>

<style scoped>
.media-workspace { position: relative; min-height: 100%; }
.media-aurora { inset: -24px -28px; }
.page-header, .review-alert, .upload-panel, .asset-section { position: relative; z-index: 1; }
.page-header { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 20px; }
.page-header h2 { margin: 8px 0 4px; font-size: 24px; color: var(--text-primary); }
.page-header p, .section-heading span, .asset-info span { margin: 0; color: var(--text-secondary); }
.review-alert { margin-bottom: 16px; }
.upload-panel { padding: 18px; margin-bottom: 24px; }
.upload-entries { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 16px; align-items: stretch; }
.portal-entry { display: grid; place-content: center; justify-items: center; gap: 6px; border: 1px dashed var(--color-primary); border-radius: 8px; color: var(--color-primary-hover); background: var(--color-primary-light); cursor: pointer; transition: background 180ms ease; }
.portal-entry:hover:not(:disabled) { background: rgba(212, 148, 28, 0.18); }
.portal-entry:disabled { cursor: not-allowed; opacity: 0.55; }
.portal-entry-icon { font-size: 34px; color: var(--color-primary); }
.portal-entry span { color: var(--text-secondary); font-size: 12px; }
@media (max-width: 700px) { .upload-entries { grid-template-columns: minmax(0, 1fr); } }
.upload-icon { font-size: 42px; color: var(--color-primary); }
.upload-tip { color: var(--text-secondary); }
.queue-list { margin-top: 16px; display: grid; gap: 8px; }
.queue-item { display: grid; grid-template-columns: minmax(160px, 1fr) 2fr; align-items: center; gap: 16px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.section-heading h3 { margin: 0 0 4px; }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 16px; }
.asset-card { overflow: hidden; padding-bottom: 12px; }
.asset-card img, .asset-card video { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; background: var(--page-bg); cursor: pointer; }
.asset-info { padding: 12px 14px 4px; display: grid; gap: 5px; }
.asset-info strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-card .glass-button { margin-left: 10px; }
@media (max-width: 700px) { .page-header, .section-heading { align-items: flex-start; gap: 12px; flex-direction: column; } }
</style>
