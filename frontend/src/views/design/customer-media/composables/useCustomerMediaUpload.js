// 客户素材上传状态机：收集文件清单 → 文件夹名匹配客户标签（validate/确认弹窗/resolve）
// → 清单预览（批量/单文件赋标签）→ 逐文件上传（tags_json）→ 完成后清单保留可继续 PATCH 编辑。
// 目录归组行为保持现状：仅顶层文件夹名归入客户目录，标签走独立的客户标签体系。
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  resolveCustomerTags,
  updateMediaAssetTags,
  uploadMediaAsset,
  validateCustomerTags,
} from '@/api/customerMedia'
import { uploadDirectoryOptions } from '../droppedFiles'
import { groupTagsByDimension, unionTags } from '../customerMediaTags'

let uidSeq = 0

export function useCustomerMediaUpload({ getBatch, onBatch, dimensions }) {
  const items = ref([])
  const validating = ref(false)
  const uploading = ref(false)
  const confirmVisible = ref(false)
  const confirming = ref(false)
  const confirmResult = ref(null)
  // 文件夹名 → 标签 {dimension_id, dimension_label, tag_value_id, value}，跨多次拖入累积复用
  const folderTagMapping = reactive({})
  // 批量赋标签（追加到全部待上传文件）
  const batchTags = ref([])
  let awaitingItems = []

  const busy = computed(() => uploading.value || validating.value)
  const pendingCount = computed(() => items.value.filter(item => item.status === 'pending').length)
  const hasItems = computed(() => items.value.length > 0)

  function folderTagsOf(item) {
    return item.pathSegments.map(name => folderTagMapping[name]).filter(Boolean)
  }

  function effectiveTags(item) {
    if (item.status === 'done') return item.finalTags
    return unionTags([folderTagsOf(item), batchTags.value, item.extraTags], dimensions.value)
  }

  function makeItem(raw) {
    const isImage = raw.file.type?.startsWith('image/')
    return {
      uid: `${Date.now()}-${uidSeq++}`,
      file: raw.file,
      name: raw.file.name,
      displayPath: [...(raw.pathSegments || []), raw.file.name].join('/'),
      directoryName: raw.directoryName || '',
      pathSegments: raw.pathSegments || [],
      previewUrl: URL.createObjectURL(raw.file),
      isImage,
      status: 'pending', // pending | uploading | done | error
      progress: 0,
      extraTags: [],
      finalTags: [],
      assetId: null,
    }
  }

  function appendItems(rawItems) {
    const seen = new Set(items.value.map(item => `${item.displayPath}:${item.file.size}`))
    const fresh = rawItems.filter(raw => !seen.has(`${[...(raw.pathSegments || []), raw.file.name].join('/')}:${raw.file.size}`))
    if (fresh.length < rawItems.length) ElMessage.info(`已跳过 ${rawItems.length - fresh.length} 个重复文件`)
    if (fresh.length) items.value.push(...fresh.map(makeItem))
  }

  /**
   * 入清单：rawItems = [{file, directoryName, pathSegments}]
   * 所有层级文件夹名去重后调 validate；有待确认项时弹确认弹窗，否则直接入清单。
   */
  async function addFiles(rawItems) {
    if (!rawItems.length) return
    const names = [...new Set(rawItems.flatMap(raw => raw.pathSegments || []).filter(Boolean))]
      .filter(name => !(name in folderTagMapping))
    if (!names.length) {
      appendItems(rawItems)
      return
    }
    validating.value = true
    try {
      const res = await validateCustomerTags(names)
      const result = res.data || {}
      // matched 直接复用，无需用户确认
      for (const match of result.matched || []) {
        folderTagMapping[match.tag_name] = {
          dimension_id: match.dimension_id,
          dimension_label: match.dimension_label || '',
          tag_value_id: match.tag_value_id,
          value: match.original_value ?? match.tag_name,
        }
      }
      const pending = (result.suggested?.length || 0) + (result.ambiguous?.length || 0) + (result.missing?.length || 0)
      if (!pending) {
        appendItems(rawItems)
        return
      }
      confirmResult.value = result
      awaitingItems = rawItems
      confirmVisible.value = true
    } catch {
      // 标签匹配不阻断上传：文件仍可入清单，之后手动补标签
      ElMessage.warning('文件夹标签匹配失败，本次文件将不带文件夹标签（可稍后手动补标）')
      appendItems(rawItems)
    } finally {
      validating.value = false
    }
  }

  // 确认弹窗「确认并继续」：selected 直接落映射，creates 先调 resolve 幂等新建
  async function confirmResolutions({ selected, creates }) {
    confirming.value = true
    try {
      Object.assign(folderTagMapping, selected)
      const createNames = Object.keys(creates || {})
      if (createNames.length) {
        const res = await resolveCustomerTags(creates)
        const mapping = res.data?.tag_mapping || {}
        for (const [name, mapped] of Object.entries(mapping)) {
          const dim = (dimensions.value || []).find(d => d.id === mapped.dimension_id)
          folderTagMapping[name] = {
            dimension_id: mapped.dimension_id,
            dimension_label: dim?.label || '',
            tag_value_id: mapped.tag_value_id,
            value: name,
          }
          // 新建的标签值同步进维度列表，后续手动选标签立即可见
          if (dim && !(dim.values || []).some(v => v.id === mapped.tag_value_id)) {
            dim.values = [...(dim.values || []), { id: mapped.tag_value_id, value: name }]
          }
        }
      }
      appendItems(awaitingItems)
      awaitingItems = []
      confirmVisible.value = false
      confirmResult.value = null
    } catch {
      // 拦截器已提示；弹窗保持打开供重试
    } finally {
      confirming.value = false
    }
  }

  // 弹窗被取消（未确认）：放弃本批文件，不进入清单
  function cancelConfirm() {
    if (awaitingItems.length) ElMessage.info('已取消，本批文件未加入清单')
    awaitingItems = []
    confirmResult.value = null
  }

  function removeItem(item) {
    if (item.status === 'uploading') return
    URL.revokeObjectURL(item.previewUrl)
    items.value = items.value.filter(row => row.uid !== item.uid)
  }

  function clearItems() {
    if (uploading.value) return
    for (const item of items.value) URL.revokeObjectURL(item.previewUrl)
    items.value = []
  }

  function reset() {
    clearItems()
    Object.keys(folderTagMapping).forEach(key => delete folderTagMapping[key])
    batchTags.value = []
    awaitingItems = []
    confirmVisible.value = false
    confirmResult.value = null
  }

  async function uploadItem(item) {
    const batchId = getBatch()?.id
    if (!batchId || item.status === 'uploading') return
    item.status = 'uploading'
    item.progress = 0
    const beforeIds = new Set((getBatch()?.assets || []).map(asset => asset.id))
    const tags = groupTagsByDimension(effectiveTags({ ...item, status: 'pending' }))
    try {
      const res = await uploadMediaAsset(batchId, item.file, event => {
        item.progress = event.total ? Math.round(event.loaded / event.total * 100) : 0
      }, { ...uploadDirectoryOptions(item.file, item.directoryName), tags })
      item.progress = 100
      item.status = 'done'
      item.finalTags = effectiveTags({ ...item, status: 'pending' })
      const created = (res.data?.assets || []).find(asset => !beforeIds.has(asset.id))
      item.assetId = created?.id ?? null
      if (created?.tags?.length) item.finalTags = created.tags
      onBatch?.(res.data)
    } catch {
      item.status = 'error'
    }
  }

  // 逐文件上传全部待传项；单文件失败不中断后续，清单保留可重试
  async function startUpload() {
    if (uploading.value) return
    uploading.value = true
    try {
      for (const item of items.value) {
        if (item.status === 'pending') await uploadItem(item)
      }
    } finally {
      uploading.value = false
    }
    const failed = items.value.filter(item => item.status === 'error').length
    const done = items.value.filter(item => item.status === 'done').length
    if (failed) ElMessage.warning(`${done} 个文件已上传，${failed} 个失败，可在清单中重试`)
    else if (done) ElMessage.success(`已上传 ${done} 个文件，可继续为图片编辑标签`)
  }

  async function retryItem(item) {
    if (item.status !== 'error' || uploading.value) return
    uploading.value = true
    try {
      await uploadItem(item)
    } finally {
      uploading.value = false
    }
  }

  // 已上传文件「编辑标签」：PATCH 按维度全量覆盖
  async function saveAssetTags(item, { tags, flat }) {
    if (!item.assetId) return false
    try {
      await updateMediaAssetTags(getBatch()?.id, item.assetId, tags)
      item.finalTags = flat
      ElMessage.success('标签已更新')
      return true
    } catch {
      return false
    }
  }

  return {
    items, validating, uploading, busy, pendingCount, hasItems,
    confirmVisible, confirming, confirmResult, folderTagMapping, batchTags,
    folderTagsOf, effectiveTags,
    addFiles, confirmResolutions, cancelConfirm,
    removeItem, clearItems, reset,
    startUpload, retryItem, saveAssetTags,
  }
}
