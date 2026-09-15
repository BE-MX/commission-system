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
            :disabled="!editable || busy"
            accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm"
            :on-change="queueFile"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入图片、视频或文件夹，或点击选择文件</div>
            <template #tip>
              <div class="upload-tip">支持 JPG、PNG、WebP、GIF、MP4、MOV、WebM；可整体拖入文件夹（含多级目录），同名目录自动归入；文件夹名会自动匹配为客户标签。原件上传，不做在线编辑。</div>
            </template>
          </el-upload>
        </div>
        <div class="entry-side">
          <button type="button" class="portal-entry" :disabled="!editable || busy" @click="folderInput?.click()">
            <el-icon class="portal-entry-icon"><Folder /></el-icon>
            <strong>选择文件夹</strong>
            <span>支持多级 / 多个文件夹</span>
          </button>
          <button type="button" class="portal-entry" :disabled="!batch" @click="showDirectoryDialog = true">
            <el-icon class="portal-entry-icon"><FolderOpened /></el-icon>
            <strong>客户素材门户</strong>
            <span>按目录管理 / 上传素材</span>
          </button>
        </div>
        <input ref="folderInput" type="file" webkitdirectory multiple hidden @change="onFolderSelected" />
      </div>
      <div v-if="validating" class="validating-hint">正在匹配文件夹标签…</div>
    </section>

    <section v-if="hasItems" class="manifest-section">
      <div class="section-heading">
        <div>
          <h3>上传清单</h3>
          <span>{{ items.length }} 个文件 · 待传 {{ pendingCount }} 个</span>
          <p class="manifest-hint">客户标签会展示在客户素材门户，命名即对外可见。</p>
        </div>
        <div class="manifest-actions">
          <GlassButton
            v-if="pendingCount"
            variant="secondary"
            left-icon="PriceTag"
            :disabled="!editable || busy"
            @click="openBatchTagPicker"
          >批量赋标签</GlassButton>
          <GlassButton
            v-if="pendingCount"
            variant="primary"
            left-icon="Upload"
            :disabled="!editable || busy"
            @click="startUpload"
          >开始上传（{{ pendingCount }}）</GlassButton>
          <GlassButton variant="ghost" left-icon="Delete" :disabled="busy" @click="clearItems">清空清单</GlassButton>
        </div>
      </div>
      <div v-if="batchTags.length" class="batch-tags">
        <span>批量标签：</span>
        <el-tag
          v-for="tag in batchTags"
          :key="`${tag.dimension_id}-${tag.tag_value_id}`"
          size="small"
          effect="plain"
          type="warning"
          class="tag-chip"
        >{{ tagLabel(tag) }}</el-tag>
      </div>

      <div class="manifest-list">
        <div v-for="item in items" :key="item.uid" class="manifest-row" :class="`is-${item.status}`">
          <div class="manifest-thumb">
            <img v-if="item.isImage" :src="item.previewUrl" :alt="item.name" />
            <video v-else :src="item.previewUrl" muted preload="metadata" />
            <span v-if="item.status === 'done'" class="status-mark done">✓</span>
            <span v-else-if="item.status === 'error'" class="status-mark error">!</span>
          </div>
          <div class="manifest-info">
            <strong :title="item.displayPath">{{ item.displayPath }}</strong>
            <div class="manifest-meta">
              <el-tag size="small" effect="plain" :type="item.directoryName ? 'warning' : 'info'">{{ item.directoryName || '未分类' }}</el-tag>
              <el-tag
                v-for="tag in displayTags(item).slice(0, 6)"
                :key="`${tag.dimension_id}-${tag.tag_value_id}`"
                size="small"
                effect="plain"
                class="tag-chip"
              >{{ tagLabel(tag) }}</el-tag>
              <span v-if="displayTags(item).length > 6" class="tags-more">+{{ displayTags(item).length - 6 }}</span>
            </div>
          </div>
          <div class="manifest-ops">
            <el-progress
              v-if="item.status === 'uploading'"
              :percentage="item.progress"
              :stroke-width="6"
              class="row-progress"
            />
            <template v-else-if="item.status === 'pending'">
              <el-button link type="primary" :disabled="busy" @click="openItemTagPicker(item)">标签</el-button>
              <el-button link type="danger" :disabled="busy" @click="removeItem(item)">移除</el-button>
            </template>
            <template v-else-if="item.status === 'done'">
              <el-button v-if="editable && item.assetId" link type="primary" @click="openAssetTagPicker(item)">编辑标签</el-button>
            </template>
            <template v-else-if="item.status === 'error'">
              <el-button link type="primary" :disabled="busy" @click="retryItem(item)">重试</el-button>
              <el-button link type="danger" :disabled="busy" @click="removeItem(item)">移除</el-button>
            </template>
          </div>
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
    <CustomerMediaTagConfirmDialog
      :model-value="confirmVisible"
      :result="confirmResult"
      :dimensions="tagDimensions"
      :confirming="confirming"
      @update:model-value="onConfirmDialogToggle"
      @confirm="confirmResolutions"
    />
    <CustomerMediaTagPicker
      v-model="pickerVisible"
      :title="pickerTitle"
      :dimensions="tagDimensions"
      :tags="pickerTags"
      :saving="pickerSaving"
      hint="客户标签会展示在客户素材门户，命名即对外可见。"
      @save="onPickerSave"
      @created="onTagCreated"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Folder, FolderOpened, UploadFilled } from '@element-plus/icons-vue'
import {
  deleteMediaAsset,
  getCustomerTagDimensions,
  getTaskMediaBatch,
  submitMediaBatch,
} from '@/api/customerMedia'
import CustomerMediaDirectoryDialog from './customer-media/CustomerMediaDirectoryDialog.vue'
import CustomerMediaTagConfirmDialog from './customer-media/CustomerMediaTagConfirmDialog.vue'
import CustomerMediaTagPicker from './customer-media/CustomerMediaTagPicker.vue'
import { collectDroppedFiles, dropHasDirectory, webkitPathSegments } from './customer-media/droppedFiles'
import { useCustomerMediaUpload } from './customer-media/composables/useCustomerMediaUpload'

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.taskId)
const batch = ref(null)
const submitting = ref(false)
const previewUrl = ref('')
const showDirectoryDialog = ref(false)
const folderInput = ref(null)
const tagDimensions = ref([])

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

const {
  items, validating, uploading, busy, pendingCount, hasItems,
  confirmVisible, confirming, confirmResult, batchTags,
  effectiveTags,
  addFiles, confirmResolutions, cancelConfirm,
  removeItem, clearItems, reset,
  startUpload, retryItem, saveAssetTags,
} = useCustomerMediaUpload({
  getBatch: () => batch.value,
  onBatch: data => { batch.value = data },
  dimensions: tagDimensions,
})

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

async function loadTagDimensions() {
  try {
    const res = await getCustomerTagDimensions()
    tagDimensions.value = res.data || []
  } catch {
    // 维度加载失败不阻断上传，只是不能打标签
  }
}

function directoryLabel(asset) {
  if (!asset.directory_id) return '未分类'
  return directories.value.find(d => d.id === asset.directory_id)?.name || '未分类'
}

function tagLabel(tag) {
  return tag.dimension_label ? `${tag.dimension_label}：${tag.value}` : tag.value
}

function displayTags(item) {
  return effectiveTags(item)
}

const FOLDER_ACCEPT_RE = /\.(jpe?g|png|webp|gif|mp4|mov|webm)$/i

function filterAccepted(files) {
  const accepted = files.filter(({ file }) => FOLDER_ACCEPT_RE.test(file.name))
  const skipped = files.length - accepted.length
  if (skipped > 0) ElMessage.warning(`已忽略 ${skipped} 个不支持的文件（仅支持 JPG、PNG、WebP、GIF、MP4、MOV、WebM）`)
  return accepted
}

// el-upload 点选/拖入散文件：无文件夹层级，直接进入清单
function queueFile(uploadFile) {
  if (!editable.value || busy.value) return
  addFiles([{ file: uploadFile.raw, directoryName: '', pathSegments: [] }])
}

async function onDropFolders(e) {
  if (!editable.value || busy.value) return
  if (!dropHasDirectory(e.dataTransfer)) return
  // 命中文件夹时拦截事件，自行递归遍历；纯文件仍交给 el-upload 处理
  e.preventDefault()
  e.stopPropagation()
  const { files } = await collectDroppedFiles(e.dataTransfer)
  addFiles(filterAccepted(files))
}

function onFolderSelected(event) {
  const files = [...event.target.files]
  event.target.value = ''
  if (!editable.value || busy.value) return
  const rawItems = files.map(file => {
    const pathSegments = webkitPathSegments(file)
    return { file, directoryName: pathSegments[0] || '', pathSegments }
  })
  addFiles(filterAccepted(rawItems))
}

function onConfirmDialogToggle(visible) {
  confirmVisible.value = visible
  if (!visible) cancelConfirm()
}

// ── 标签选择弹窗（批量 / 单文件追加 / 已上传编辑 共用） ──
const pickerVisible = ref(false)
const pickerSaving = ref(false)
const pickerTarget = ref(null) // {kind: 'batch'} | {kind: 'item'|'asset', item}
const pickerTitle = computed(() => ({
  batch: '批量赋标签',
  item: `追加标签 · ${pickerTarget.value?.item?.name || ''}`,
  asset: `编辑标签 · ${pickerTarget.value?.item?.name || ''}`,
}[pickerTarget.value?.kind] || '编辑标签'))
const pickerTags = computed(() => {
  const target = pickerTarget.value
  if (!target) return []
  if (target.kind === 'batch') return batchTags.value
  if (target.kind === 'asset') return target.item.finalTags
  return target.item.extraTags
})

function openBatchTagPicker() {
  pickerTarget.value = { kind: 'batch' }
  pickerVisible.value = true
}

function openItemTagPicker(item) {
  pickerTarget.value = { kind: 'item', item }
  pickerVisible.value = true
}

function openAssetTagPicker(item) {
  pickerTarget.value = { kind: 'asset', item }
  pickerVisible.value = true
}

async function onPickerSave({ tags, flat }) {
  const target = pickerTarget.value
  if (!target) return
  if (target.kind === 'batch') {
    batchTags.value = flat
    ElMessage.success('批量标签已应用到全部待传文件')
  } else if (target.kind === 'item') {
    target.item.extraTags = flat
  } else {
    pickerSaving.value = true
    try {
      if (!await saveAssetTags(target.item, { tags, flat })) return
    } finally { pickerSaving.value = false }
  }
  pickerVisible.value = false
}

// 行内新建标签后同步进维度列表，保证后续打开的选择器立即可见
function onTagCreated({ dimension_id, value }) {
  const dim = tagDimensions.value.find(d => d.id === dimension_id)
  if (dim && !(dim.values || []).some(v => v.id === value.id)) {
    dim.values = [...(dim.values || []), value]
  }
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
onMounted(() => {
  loadBatch()
  loadTagDimensions()
})
onBeforeUnmount(reset)
</script>

<style scoped>
.media-workspace { position: relative; min-height: 100%; }
.media-aurora { inset: -24px -28px; }
.page-header, .review-alert, .upload-panel, .manifest-section, .asset-section { position: relative; z-index: 1; }
.page-header { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 20px; }
.page-header h2 { margin: 8px 0 4px; font-size: 24px; color: var(--text-primary); }
.page-header p, .section-heading span, .asset-info span { margin: 0; color: var(--text-secondary); }
.review-alert { margin-bottom: 16px; }
.upload-panel { padding: 18px; margin-bottom: 24px; }
.upload-entries { display: grid; grid-template-columns: minmax(0, 1fr) 220px; gap: 16px; align-items: stretch; }
.entry-side { display: grid; gap: 16px; }
.portal-entry { display: grid; place-content: center; justify-items: center; gap: 6px; border: 1px dashed var(--color-primary); border-radius: 8px; color: var(--color-primary-hover); background: var(--color-primary-light); cursor: pointer; transition: background 180ms ease; }
.portal-entry:hover:not(:disabled) { background: rgba(212, 148, 28, 0.18); }
.portal-entry:disabled { cursor: not-allowed; opacity: 0.55; }
.portal-entry-icon { font-size: 34px; color: var(--color-primary); }
.portal-entry span { color: var(--text-secondary); font-size: 12px; }
@media (max-width: 700px) { .upload-entries { grid-template-columns: minmax(0, 1fr); } }
.upload-icon { font-size: 42px; color: var(--color-primary); }
.upload-tip { color: var(--text-secondary); }
.validating-hint { margin-top: 14px; color: var(--text-secondary); font-size: 12px; }
.manifest-section { margin-bottom: 24px; padding: 18px; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow); }
.manifest-hint { margin: 4px 0 0; color: var(--text-secondary); font-size: 12px; }
.manifest-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.batch-tags { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 12px; color: var(--text-secondary); font-size: 12px; }
.manifest-list { display: grid; gap: 10px; max-height: 480px; overflow-y: auto; }
.manifest-row { display: grid; grid-template-columns: 72px minmax(0, 1fr) auto; align-items: center; gap: 14px; padding: 10px 12px; border: 1px solid var(--border-color); border-radius: 10px; background: var(--card-bg); }
.manifest-row.is-error { border-color: var(--color-danger); }
.manifest-thumb { position: relative; width: 72px; height: 54px; overflow: hidden; border-radius: 6px; background: var(--page-bg); }
.manifest-thumb img, .manifest-thumb video { width: 100%; height: 100%; object-fit: cover; }
.status-mark { position: absolute; right: 3px; bottom: 3px; display: grid; width: 18px; height: 18px; place-items: center; border-radius: 50%; color: #fff; font-size: 11px; }
.status-mark.done { background: var(--color-success); }
.status-mark.error { background: var(--color-danger); }
.manifest-info { display: grid; min-width: 0; gap: 6px; }
.manifest-info strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.manifest-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; }
.tag-chip { max-width: 180px; overflow: hidden; text-overflow: ellipsis; }
.tags-more { color: var(--text-secondary); font-size: 12px; }
.manifest-ops { display: flex; align-items: center; gap: 4px; }
.row-progress { width: 160px; }
.section-heading { display: flex; align-items: center; justify-content: space-between; margin-bottom: 16px; }
.section-heading h3 { margin: 0 0 4px; }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(230px, 1fr)); gap: 16px; }
.asset-card { overflow: hidden; padding-bottom: 12px; }
.asset-card img, .asset-card video { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; background: var(--page-bg); cursor: pointer; }
.asset-info { padding: 12px 14px 4px; display: grid; gap: 5px; }
.asset-info strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-card .glass-button { margin-left: 10px; }
@media (max-width: 700px) { .page-header, .section-heading { align-items: flex-start; gap: 12px; flex-direction: column; } .manifest-row { grid-template-columns: 56px minmax(0, 1fr); } .manifest-ops { grid-column: 1 / -1; justify-content: flex-end; } }
</style>
