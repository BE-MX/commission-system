<template>
  <el-dialog
    :model-value="modelValue"
    title="客户素材门户"
    width="1080px"
    top="6vh"
    @update:model-value="$emit('update:modelValue', $event)"
  >
    <div v-if="batch" class="portal-dialog">
      <aside class="dir-sidebar">
        <div class="dir-create">
          <el-input
            v-model="newDirName"
            size="small"
            maxlength="128"
            placeholder="新建目录名称"
            :disabled="!editable"
            @keyup.enter="createDir"
          />
          <el-button size="small" type="primary" :disabled="!editable || !newDirName.trim()" :loading="creating" @click="createDir">新建</el-button>
        </div>
        <div class="dir-list">
          <button type="button" :class="['dir-row', { active: selected === 'all' }]" @click="selected = 'all'">
            <span class="dir-name">全部素材</span><span class="dir-count">{{ assets.length }}</span>
          </button>
          <button type="button" :class="['dir-row', { active: selected === null }]" @click="selected = null">
            <span class="dir-name">未分类</span><span class="dir-count">{{ uncategorizedCount }}</span>
          </button>
          <div v-for="dir in directories" :key="dir.id" class="dir-row-wrap">
            <div v-if="renamingId === dir.id" class="dir-rename">
              <el-input v-model="renamingName" size="small" maxlength="128" @keyup.enter="confirmRename" @keyup.esc="renamingId = null" />
              <el-button size="small" type="primary" link :loading="renaming" @click="confirmRename">确定</el-button>
              <el-button size="small" link @click="renamingId = null">取消</el-button>
            </div>
            <button v-else type="button" :class="['dir-row', { active: selected === dir.id }]" @click="selected = dir.id">
              <span class="dir-name" :title="dir.name">{{ dir.name }}</span>
              <span class="dir-count">{{ dir.asset_count }}</span>
              <el-icon v-if="editable" class="dir-edit" title="重命名" @click.stop="startRename(dir)"><Edit /></el-icon>
            </button>
          </div>
          <div v-if="!directories.length" class="dir-empty">尚无目录，可在上方新建</div>
        </div>
      </aside>

      <div class="dir-content">
        <div v-if="editable" class="upload-drop" @drop.capture="onDropFolders">
          <el-upload
            drag
            multiple
            :auto-upload="false"
            :show-file-list="false"
            :disabled="uploading"
            accept="image/jpeg,image/png,image/webp,image/gif,video/mp4,video/quicktime,video/webm"
            :on-change="queueFile"
          >
            <div class="el-upload__text">拖入文件或文件夹，上传到「{{ selectedLabel }}」</div>
          </el-upload>
        </div>
        <div v-if="uploadQueue.length" class="queue-list">
          <div v-for="item in uploadQueue" :key="item.uid" class="queue-item">
            <span>{{ item.name }}</span>
            <el-progress :percentage="item.progress" :status="item.error ? 'exception' : item.done ? 'success' : ''" />
          </div>
        </div>

        <div v-if="filteredAssets.length" class="asset-grid">
          <article v-for="asset in filteredAssets" :key="asset.id" class="asset-card">
            <img v-if="asset.media_type === 'image'" :src="asset.content_url" :alt="asset.file_name" @click="previewUrl = asset.content_url" />
            <video v-else :src="asset.content_url" controls preload="metadata" />
            <div class="asset-info">
              <strong :title="asset.file_name">{{ asset.file_name }}</strong>
              <span>{{ formatSize(asset.file_size) }}</span>
            </div>
            <el-button v-if="editable" link type="danger" size="small" @click="removeAsset(asset)">删除</el-button>
          </article>
        </div>
        <el-empty v-else :description="`「${selectedLabel}」暂无素材`" />
      </div>
    </div>

    <el-image-viewer v-if="previewUrl" :url-list="[previewUrl]" @close="previewUrl = ''" />
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit } from '@element-plus/icons-vue'
import {
  createMediaDirectory, deleteMediaAsset, getTaskMediaBatch,
  renameMediaDirectory, uploadMediaAsset,
} from '@/api/customerMedia'
import { collectDroppedFiles, dropHasDirectory } from './droppedFiles'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  batch: { type: Object, default: null },
  editable: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'update:batch'])

const ALL = 'all'
const selected = ref(ALL)
const newDirName = ref('')
const creating = ref(false)
const renamingId = ref(null)
const renamingName = ref('')
const renaming = ref(false)
const uploading = ref(false)
const uploadQueue = ref([])
const previewUrl = ref('')

const assets = computed(() => props.batch?.assets || [])
const directories = computed(() => props.batch?.directories || [])
const uncategorizedCount = computed(() => assets.value.filter(a => !a.directory_id).length)
const filteredAssets = computed(() => {
  if (selected.value === ALL) return assets.value
  if (selected.value === null) return assets.value.filter(a => !a.directory_id)
  return assets.value.filter(a => a.directory_id === selected.value)
})
const selectedLabel = computed(() => {
  if (selected.value === ALL) return '全部素材'
  if (selected.value === null) return '未分类'
  return directories.value.find(d => d.id === selected.value)?.name || '未分类'
})

watch(() => props.modelValue, visible => {
  if (visible) {
    selected.value = ALL
    renamingId.value = null
    newDirName.value = ''
  }
})

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}

async function refreshBatch() {
  const res = await getTaskMediaBatch(props.batch.task_id)
  emit('update:batch', res.data)
}

async function createDir() {
  const name = newDirName.value.trim()
  if (!name || creating.value) return
  creating.value = true
  try {
    await createMediaDirectory(props.batch.id, name)
    newDirName.value = ''
    await refreshBatch()
    ElMessage.success('目录已就绪')
  } finally { creating.value = false }
}

function startRename(dir) {
  renamingId.value = dir.id
  renamingName.value = dir.name
}

async function confirmRename() {
  const name = renamingName.value.trim()
  if (!name || renaming.value) return
  renaming.value = true
  try {
    await renameMediaDirectory(props.batch.id, renamingId.value, name)
    renamingId.value = null
    await refreshBatch()
    ElMessage.success('目录已重命名')
  } finally { renaming.value = false }
}

function targetDirectoryOptions() {
  // 上传目标固定为当前选中目录；「全部/未分类」视图下归入未分类
  return typeof selected.value === 'number' ? { directoryId: selected.value } : {}
}

async function uploadOne(item, file) {
  try {
    const res = await uploadMediaAsset(props.batch.id, file, event => {
      item.progress = event.total ? Math.round(event.loaded / event.total * 100) : 0
    }, targetDirectoryOptions())
    item.progress = 100
    item.done = true
    emit('update:batch', res.data)
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

function warnIfAllSelected() {
  if (selected.value === ALL) ElMessage.info('当前为「全部素材」视图，文件将归入未分类')
}

async function queueFile(uploadFile) {
  if (!props.editable) return
  warnIfAllSelected()
  uploading.value = true
  const item = pushQueueItem(uploadFile.name)
  await uploadOne(item, uploadFile.raw)
  uploading.value = uploadQueue.value.some(row => !row.done && !row.error)
  scheduleQueueCleanup()
}

const FOLDER_ACCEPT_RE = /\.(jpe?g|png|webp|gif|mp4|mov|webm)$/i

async function onDropFolders(e) {
  if (!props.editable || uploading.value) return
  if (!dropHasDirectory(e.dataTransfer)) return
  // 弹窗内文件夹拖入统一归入当前选中目录，不再按文件夹名建目录
  e.preventDefault()
  e.stopPropagation()
  const { files } = await collectDroppedFiles(e.dataTransfer)
  const accepted = files.filter(({ file }) => FOLDER_ACCEPT_RE.test(file.name))
  const skipped = files.length - accepted.length
  if (skipped > 0) ElMessage.warning(`已忽略 ${skipped} 个不支持的文件（仅支持 JPG、PNG、WebP、GIF、MP4、MOV、WebM）`)
  if (!accepted.length) return
  warnIfAllSelected()
  uploading.value = true
  for (const { file } of accepted) {
    const item = pushQueueItem(file.name)
    await uploadOne(item, file)
  }
  uploading.value = uploadQueue.value.some(row => !row.done && !row.error)
  scheduleQueueCleanup()
}

async function removeAsset(asset) {
  try { await ElMessageBox.confirm(`删除 ${asset.file_name}？`, '删除素材', { type: 'warning' }) } catch { return }
  const res = await deleteMediaAsset(props.batch.id, asset.id)
  emit('update:batch', res.data)
  ElMessage.success('已删除')
}
</script>

<style scoped>
.portal-dialog { display: grid; grid-template-columns: 240px minmax(0, 1fr); gap: 18px; min-height: 480px; max-height: 72vh; }
.dir-sidebar { display: flex; min-height: 0; flex-direction: column; border-right: 1px solid var(--border-color); padding-right: 14px; }
.dir-create { display: flex; gap: 8px; margin-bottom: 12px; }
.dir-list { flex: 1; overflow-y: auto; display: grid; gap: 4px; align-content: start; }
.dir-row { display: flex; width: 100%; align-items: center; gap: 8px; padding: 8px 10px; border: 0; border-radius: 8px; color: var(--text-primary); background: transparent; cursor: pointer; text-align: left; font-size: 13px; }
.dir-row:hover { background: var(--color-primary-light); }
.dir-row.active { background: var(--color-primary-light); color: var(--color-primary-hover); font-weight: 600; }
.dir-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.dir-count { color: var(--text-secondary); font-size: 12px; }
.dir-edit { flex: 0 0 auto; color: var(--text-secondary); }
.dir-edit:hover { color: var(--color-primary); }
.dir-rename { display: flex; align-items: center; gap: 4px; padding: 2px 0; }
.dir-empty { padding: 18px 8px; color: var(--text-secondary); font-size: 12px; text-align: center; }
.dir-content { min-width: 0; overflow-y: auto; padding-right: 4px; }
.upload-drop { margin-bottom: 14px; }
.queue-list { margin-bottom: 14px; display: grid; gap: 8px; }
.queue-item { display: grid; grid-template-columns: minmax(160px, 1fr) 2fr; align-items: center; gap: 16px; }
.asset-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 14px; }
.asset-card { overflow: hidden; border: 1px solid var(--border-color); border-radius: 10px; background: var(--card-bg); padding-bottom: 8px; }
.asset-card img, .asset-card video { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; background: var(--page-bg); cursor: pointer; }
.asset-info { padding: 10px 12px 2px; display: grid; gap: 4px; }
.asset-info strong { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 13px; }
.asset-info span { color: var(--text-secondary); font-size: 12px; }
.asset-card .el-button { margin-left: 10px; }
@media (max-width: 860px) { .portal-dialog { grid-template-columns: minmax(0, 1fr); } .dir-sidebar { border-right: 0; border-bottom: 1px solid var(--border-color); padding: 0 0 12px; } }
</style>
