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
      <div class="header-actions">
        <el-tag v-if="batch" :type="statusMeta.type" effect="plain">{{ statusMeta.label }}</el-tag>
        <GlassButton v-if="editable" variant="primary" left-icon="Upload" @click="uploadDialog = true">上传素材</GlassButton>
        <GlassButton v-if="batch?.directories?.length" variant="secondary" left-icon="FolderOpened" @click="showDirectoryDialog = true">管理旧目录</GlassButton>
      </div>
    </header>

    <el-alert
      v-if="batch?.status === 'changes_requested'"
      :title="`审核退回：${batch.review_comment}`"
      type="warning"
      show-icon
      :closable="false"
      class="review-alert"
    />

    <el-dialog v-model="uploadDialog" title="上传客户拍摄素材" width="min(900px, 94vw)" :before-close="beforeUploadClose">
      <CustomerTagBoard
        :dimensions="tagDimensions"
        :tags="customerTags"
        :selected-tag-ids="selectedTagIds"
        selectable
        :disabled="busy"
        @add="tagPickerVisible = true"
        @toggle="toggleTag"
      />
      <p class="upload-selection-hint">已选 {{ selectedTagIds.length }} 个标签。先选标签，再添加文件；本次所选标签会关联到添加的每个文件。</p>
    <section class="upload-panel lg-card">
      <div class="upload-entries">
        <div class="upload-drop" @drop.capture="onDropFolders">
          <el-upload
            drag
            multiple
            :auto-upload="false"
            :show-file-list="false"
            :disabled="!editable || busy || !selectedTagIds.length"
            accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm"
            :on-change="queueFile"
          >
            <el-icon class="upload-icon"><UploadFilled /></el-icon>
            <div class="el-upload__text">拖入图片、视频或文件夹，或点击选择文件</div>
            <template #tip>
              <div class="upload-tip">文件夹只用于一次选择多个文件；不会根据文件夹名称创建目录或标签。支持 JPG、PNG、WebP、GIF、MP4、MOV、WebM。</div>
            </template>
          </el-upload>
        </div>
        <div class="entry-side">
          <button type="button" class="portal-entry" :disabled="!editable || busy || !selectedTagIds.length" @click="folderInput?.click()">
            <el-icon class="portal-entry-icon"><Folder /></el-icon>
            <strong>选择文件夹</strong>
            <span>支持多级 / 多个文件夹</span>
          </button>
        </div>
        <input ref="folderInput" type="file" webkitdirectory multiple hidden @change="onFolderSelected" />
      </div>
    </section>

    <section v-if="hasItems" class="manifest-section">
      <div class="section-heading">
        <div>
          <h3>上传清单</h3>
          <span>{{ items.length }} 个文件 · 待传 {{ pendingCount }} 个</span>
          <p class="manifest-hint">文件还未上传。每行显示的是加入清单时选中的客户标签。</p>
        </div>
        <div class="manifest-actions">
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
              <el-tag
                v-for="tag in item.tags.slice(0, 6)"
                :key="`${tag.dimension_id}-${tag.tag_value_id}`"
                size="small"
                effect="plain"
                class="tag-chip"
              >{{ tagLabel(tag) }}</el-tag>
              <span v-if="item.tags.length > 6" class="tags-more">+{{ item.tags.length - 6 }}</span>
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
              <el-button link type="danger" :disabled="busy" @click="removeItem(item)">移除</el-button>
            </template>
            <template v-else-if="item.status === 'error'">
              <el-button link type="primary" :disabled="busy" @click="retryItem(item)">重试</el-button>
              <el-button link type="danger" :disabled="busy" @click="removeItem(item)">移除</el-button>
            </template>
          </div>
        </div>
      </div>
    </section>
    </el-dialog>

    <section class="asset-section">
      <div class="section-heading">
        <div><h3>本批素材</h3><span>{{ assets.length }} 个文件 · {{ totalSize }}</span></div>
        <GlassButton
          variant="warning"
          left-icon="Promotion"
          :disabled="!editable || !assets.length || uploading || incompleteCount"
          :loading="submitting"
          @click="submitForReview"
        >完成拍摄并送审</GlassButton>
      </div>

      <div v-if="assets.length" class="dimension-groups">
        <section v-for="group in assetGroups" :key="group.id" class="asset-dimension">
          <h4>{{ group.label }}</h4>
          <div v-for="bucket in group.buckets" :key="bucket.id" class="asset-tag-group">
            <h5>{{ bucket.label }} <span>{{ bucket.assets.length }} 个文件</span></h5>
            <div class="asset-grid">
        <article v-for="asset in bucket.assets" :key="asset.id" class="asset-card lg-card">
          <img v-if="asset.media_type === 'image'" :src="asset.content_url" :alt="asset.file_name" @click="preview(asset)" />
          <video v-else :src="asset.content_url" controls preload="metadata" />
          <div class="asset-info">
            <strong :title="asset.file_name">{{ asset.file_name }}</strong>
            <span>{{ formatSize(asset.file_size) }}</span>
            <el-tag v-if="asset.directory_id" size="small" effect="plain" type="warning">旧目录：{{ directoryLabel(asset) }}</el-tag>
          </div>
          <GlassButton v-if="editable" variant="link" link-tone="danger" left-icon="Delete" @click="removeAsset(asset)">删除</GlassButton>
        </article>
            </div>
          </div>
        </section>
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
    <CustomerMediaTagPicker
      v-model="tagPickerVisible"
      title="为客户添加标签"
      :dimensions="tagDimensions"
      :saving="tagSaving"
      hint="添加后这位客户的后续预约也会显示。标签选择只作用于本次随后添加的文件。"
      @save="saveCustomerTags"
      @created="onTagCreated"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, Folder, UploadFilled } from '@element-plus/icons-vue'
import {
  addTaskCustomerTags, deleteMediaAsset, getCustomerTagDimensions,
  getTaskCustomerTags, getTaskMediaBatch, submitMediaBatch,
} from '@/api/customerMedia'
import CustomerMediaDirectoryDialog from './customer-media/CustomerMediaDirectoryDialog.vue'
import CustomerMediaTagPicker from './customer-media/CustomerMediaTagPicker.vue'
import CustomerTagBoard from './customer-media/CustomerTagBoard.vue'
import { groupMediaByTags } from './customer-media/customerMediaGrouping'
import { collectDroppedFiles, dropHasDirectory, webkitPathSegments } from './customer-media/droppedFiles'
import { useCustomerMediaUpload } from './customer-media/composables/useCustomerMediaUpload'

const route = useRoute()
const router = useRouter()
const taskId = Number(route.params.taskId)
const batch = ref(null)
const tagDimensions = ref([])
const customerTags = ref([])
const selectedTagIds = ref([])
const uploadDialog = ref(false)
const showDirectoryDialog = ref(false)
const tagPickerVisible = ref(false)
const tagSaving = ref(false)
const folderInput = ref(null)
const submitting = ref(false)
const previewUrl = ref('')

const assets = computed(() => batch.value?.assets || [])
const directories = computed(() => batch.value?.directories || [])
const editable = computed(() => ['draft', 'changes_requested'].includes(batch.value?.status))
const selectedTags = computed(() => customerTags.value.filter(tag => selectedTagIds.value.includes(tag.tag_value_id)))
const assetGroups = computed(() => groupMediaByTags(assets.value, tagDimensions.value))
const totalSize = computed(() => formatSize(assets.value.reduce((sum, item) => sum + item.file_size, 0)))
const statusMeta = computed(() => ({
  draft: { label: '整理中', type: 'info' },
  changes_requested: { label: '待修改', type: 'warning' },
  pending_review: { label: '待审核', type: 'warning' },
  published: { label: '已发布', type: 'success' },
  unpublished: { label: '已下架', type: 'info' },
}[batch.value?.status] || { label: batch.value?.status, type: 'info' }))

const {
  items, uploading, busy, pendingCount, incompleteCount, hasItems,
  addFiles, removeItem, clearItems, reset, startUpload, retryItem,
} = useCustomerMediaUpload({
  getBatch: () => batch.value,
  onBatch: data => { batch.value = data },
  getSelectedTags: () => selectedTags.value,
})

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

async function loadBatch() { batch.value = (await getTaskMediaBatch(taskId)).data }
async function loadCustomerTags() { customerTags.value = (await getTaskCustomerTags(taskId)).data || [] }
async function loadTagDimensions() { tagDimensions.value = (await getCustomerTagDimensions()).data || [] }

function directoryLabel(asset) {
  if (!asset.directory_id) return '未分类'
  return directories.value.find(d => d.id === asset.directory_id)?.name || '未分类'
}
function tagLabel(tag) { return tag.dimension_label ? `${tag.dimension_label}：${tag.value}` : tag.value }

function toggleTag(tag) {
  if (busy.value) return
  if (selectedTagIds.value.includes(tag.tag_value_id)) {
    selectedTagIds.value = selectedTagIds.value.filter(id => id !== tag.tag_value_id)
    return
  }
  const dim = tagDimensions.value.find(item => item.id === tag.dimension_id)
  if (dim?.is_single_select) {
    const sameDim = new Set(customerTags.value.filter(item => item.dimension_id === dim.id).map(item => item.tag_value_id))
    selectedTagIds.value = selectedTagIds.value.filter(id => !sameDim.has(id))
  }
  selectedTagIds.value = [...selectedTagIds.value, tag.tag_value_id]
}

async function saveCustomerTags({ tags, flat }) {
  if (!tags.some(item => item.tag_value_ids.length)) { ElMessage.warning('请选择至少一个标签'); return }
  tagSaving.value = true
  try {
    customerTags.value = (await addTaskCustomerTags(taskId, tags)).data || []
    for (const tag of flat) if (!selectedTagIds.value.includes(tag.tag_value_id)) toggleTag(tag)
    tagPickerVisible.value = false
    ElMessage.success('客户标签已保存')
  } finally { tagSaving.value = false }
}

function onTagCreated({ dimension_id, value }) {
  const dim = tagDimensions.value.find(item => item.id === dimension_id)
  if (dim && !(dim.values || []).some(item => item.id === value.id)) dim.values = [...(dim.values || []), value]
}

const FOLDER_ACCEPT_RE = /\.(jpe?g|png|webp|gif|mp4|mov|webm)$/i
function filterAccepted(files) {
  const accepted = files.filter(({ file }) => FOLDER_ACCEPT_RE.test(file.name))
  const skipped = files.length - accepted.length
  if (skipped) ElMessage.warning(`已忽略 ${skipped} 个不支持的文件`)
  return accepted
}
function queueFile(uploadFile) {
  if (!editable.value || busy.value) return
  addFiles(filterAccepted([{ file: uploadFile.raw, pathSegments: [] }]))
}
async function onDropFolders(event) {
  if (!editable.value || busy.value || !selectedTagIds.value.length) return
  if (!dropHasDirectory(event.dataTransfer)) return
  event.preventDefault()
  event.stopPropagation()
  try {
    const { files } = await collectDroppedFiles(event.dataTransfer)
    addFiles(filterAccepted(files))
  } catch (error) { ElMessage.error(`读取文件夹失败：${error.message || '请重试'}`) }
}
function onFolderSelected(event) {
  const files = [...event.target.files]
  event.target.value = ''
  if (!editable.value || busy.value || !selectedTagIds.value.length) return
  addFiles(filterAccepted(files.map(file => ({ file, pathSegments: webkitPathSegments(file) }))))
}
function beforeUploadClose(done) {
  if (busy.value) { ElMessage.warning('文件上传中，请等待完成'); return }
  done()
}

async function removeAsset(asset) {
  try { await ElMessageBox.confirm(`删除 ${asset.file_name}？`, '删除素材', { type: 'warning' }) } catch { return }
  batch.value = (await deleteMediaAsset(batch.value.id, asset.id)).data
  ElMessage.success('已删除')
}

async function submitForReview() {
  if (incompleteCount.value) { ElMessage.warning('请先上传或移除清单中的未完成文件'); return }
  try {
    await ElMessageBox.confirm(
      `本次将提交 ${assets.value.length} 个文件审核，并完成拍摄任务。审核通过后客户才能看到素材。`,
      '完成并送审', { type: 'info' },
    )
  } catch { return }
  submitting.value = true
  try {
    batch.value = (await submitMediaBatch(batch.value.id, batch.value.lock_version)).data
    ElMessage.success('已送审')
  } finally { submitting.value = false }
}

function preview(asset) { previewUrl.value = asset.content_url }
onMounted(() => { loadBatch(); loadCustomerTags(); loadTagDimensions() })
onBeforeUnmount(reset)
</script>


<style scoped>
.media-workspace { position: relative; min-height: 100%; }
.media-aurora { inset: -24px -28px; }
.page-header, .review-alert, .upload-panel, .manifest-section, .asset-section { position: relative; z-index: 1; }
.page-header { display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 20px; }
.page-header h2 { margin: 8px 0 4px; font-size: 24px; color: var(--text-primary); }
.page-header p, .section-heading span, .asset-info span { margin: 0; color: var(--text-secondary); }
.header-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
.review-alert { margin-bottom: 16px; }
.upload-selection-hint { margin: 12px 0; color: var(--text-secondary); font-size: 13px; }
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
.manifest-section { margin-bottom: 24px; padding: 18px; border: 1px solid var(--dash-glass-border); border-radius: var(--dash-card-radius); background: var(--dash-glass-bg); box-shadow: var(--dash-glass-shadow); }
.manifest-hint { margin: 4px 0 0; color: var(--text-secondary); font-size: 12px; }
.manifest-actions { display: flex; flex-wrap: wrap; gap: 8px; }
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
.dimension-groups { display: grid; gap: 26px; }
.asset-dimension { border-top: 1px solid var(--border-color); padding-top: 16px; }
.asset-dimension h4 { margin: 0 0 14px; color: var(--text-primary); font-size: 17px; }
.asset-tag-group { margin-bottom: 20px; }
.asset-tag-group h5 { margin: 0 0 12px; font-size: 14px; color: var(--color-primary-hover); }
.asset-tag-group h5 span { margin-left: 7px; color: var(--text-secondary); font-weight: 400; }
.asset-card { overflow: hidden; padding-bottom: 12px; }
.asset-card img, .asset-card video { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; background: var(--page-bg); cursor: pointer; }
.asset-info { padding: 12px 14px 4px; display: grid; gap: 5px; }
.asset-info strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.asset-card .glass-button { margin-left: 10px; }
@media (max-width: 700px) { .page-header, .section-heading { align-items: flex-start; gap: 12px; flex-direction: column; } .manifest-row { grid-template-columns: 56px minmax(0, 1fr); } .manifest-ops { grid-column: 1 / -1; justify-content: flex-end; } }
</style>
