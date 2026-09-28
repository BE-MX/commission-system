// One upload flow for loose files and folders. Folder names are display paths
// only: they never create customer labels or destination directories.
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { uploadMediaAsset } from '@/api/customerMedia'
import { groupTagsByDimension } from '../customerMediaTags'

let uidSeq = 0

export function useCustomerMediaUpload({ getBatch, onBatch, getSelectedTags }) {
  const items = ref([])
  const uploading = ref(false)
  const busy = computed(() => uploading.value)
  const pendingCount = computed(() => items.value.filter(item => item.status === 'pending').length)
  const incompleteCount = computed(() => items.value.length)
  const hasItems = computed(() => items.value.length > 0)

  function release(item) { URL.revokeObjectURL(item.previewUrl) }

  function addFiles(rawItems) {
    if (!rawItems.length) return
    const tags = (getSelectedTags() || []).map(tag => ({ ...tag }))
    if (!tags.length) { ElMessage.warning('请先选择至少一个客户标签'); return }
    const seen = new Set(items.value.map(item => `${item.displayPath}:${item.file.size}`))
    let skipped = 0
    for (const raw of rawItems) {
      const path = [...(raw.pathSegments || []), raw.file.name].join('/')
      const key = `${path}:${raw.file.size}`
      if (seen.has(key)) { skipped++; continue }
      seen.add(key)
      items.value.push({
        uid: `${Date.now()}-${uidSeq++}`,
        file: raw.file,
        name: raw.file.name,
        displayPath: path,
        previewUrl: URL.createObjectURL(raw.file),
        isImage: raw.file.type?.startsWith('image/'),
        tags,
        status: 'pending',
        progress: 0,
        error: '',
      })
    }
    if (skipped) ElMessage.info(`已跳过 ${skipped} 个重复文件`)
  }

  function removeItem(item) {
    if (item.status === 'uploading') return
    release(item)
    items.value = items.value.filter(row => row.uid !== item.uid)
  }

  function clearItems() {
    if (uploading.value) return
    items.value.forEach(release)
    items.value = []
  }

  async function uploadItem(item) {
    const batchId = getBatch()?.id
    if (!batchId || !item.tags.length) return
    item.status = 'uploading'
    item.progress = 0
    try {
      const res = await uploadMediaAsset(batchId, item.file, event => {
        item.progress = event.total ? Math.round(event.loaded / event.total * 100) : 0
      }, { tags: groupTagsByDimension(item.tags) })
      item.status = 'done'
      item.progress = 100
      onBatch?.(res.data)
    } catch (error) {
      item.status = 'error'
      item.error = error?.response?.data?.detail || '上传失败，请重试'
    }
  }

  async function startUpload() {
    if (uploading.value || !pendingCount.value) return
    uploading.value = true
    try {
      for (const item of items.value) if (item.status === 'pending') await uploadItem(item)
    } finally { uploading.value = false }
    const done = items.value.filter(item => item.status === 'done')
    done.forEach(release)
    items.value = items.value.filter(item => item.status !== 'done')
    if (items.value.length) ElMessage.warning(`${done.length} 个已上传，${items.value.length} 个失败，可重试`)
    else if (done.length) ElMessage.success(`${done.length} 个文件已上传`)
  }

  async function retryItem(item) {
    if (item.status !== 'error' || uploading.value) return
    item.status = 'pending'
    await startUpload()
  }

  return { items, uploading, busy, pendingCount, incompleteCount, hasItems,
    addFiles, removeItem, clearItems, reset: clearItems, startUpload, retryItem }
}
