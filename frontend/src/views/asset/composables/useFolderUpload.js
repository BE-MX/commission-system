import { computed, onBeforeUnmount, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  executeFolderUpload,
  getFolderUploadStatus,
  previewFolderUpload,
  uploadFolderDirect,
  validateFolderUpload,
} from '@/api/asset'

const SUPPORTED_EXTENSIONS = new Set([
  'jpg', 'jpeg', 'png', 'webp', 'heic', 'gif', 'bmp', 'tiff', 'tif',
  'mp4', 'mov', 'avi', 'mkv', 'wmv', 'flv', 'webm', 'm4v', '3gp', 'mpeg', 'mpg',
])

function extensionOf(name) {
  const parts = name.toLowerCase().split('.')
  return parts.length > 1 ? parts.pop() : ''
}

function readDirectoryEntries(reader) {
  return new Promise((resolve, reject) => {
    const entries = []
    const readBatch = () => {
      reader.readEntries((batch) => {
        if (!batch.length) {
          resolve(entries)
          return
        }
        entries.push(...batch)
        readBatch()
      }, reject)
    }
    readBatch()
  })
}

function readFileEntry(entry) {
  return new Promise((resolve, reject) => entry.file(resolve, reject))
}

async function flattenEntry(entry, parentPath = '') {
  const relativePath = parentPath ? `${parentPath}/${entry.name}` : entry.name
  if (entry.isFile) {
    const file = await readFileEntry(entry)
    return [{ file, relativePath }]
  }
  if (!entry.isDirectory) return []
  const children = await readDirectoryEntries(entry.createReader())
  const nested = await Promise.all(children.map(child => flattenEntry(child, relativePath)))
  return nested.flat()
}

export function useFolderUpload({ dimensions, canAutoCreate, onUploaded }) {
  const visible = ref(false)
  const step = ref('input')
  const selectedEntries = ref([])
  const serverPath = ref('')
  const sourceMode = ref('browser')
  const includeFilenameTags = ref(false)
  const isDragging = ref(false)
  const validationResult = ref(null)
  const previewData = ref(null)
  const uploadReport = ref(null)
  const tagMapping = ref({})
  const autoCreateTags = ref({})
  const resolutions = reactive({})
  const updateDuplicates = ref(true)
  const jobId = ref(null)
  const uploadProgress = ref(null)
  const pollError = ref('')
  const fatalMessage = ref('')
  const permission = ref({ permission_group: 'all', allow_preview: 1, allow_download: 1 })
  let pollTimer = null
  let pollFailures = 0

  const relativePaths = computed(() => selectedEntries.value.map(item => item.relativePath))
  const selectedFiles = computed(() => selectedEntries.value.map(item => item.file))
  const selectedSize = computed(() => selectedFiles.value.reduce((total, file) => total + file.size, 0))
  const rootNames = computed(() => {
    const names = relativePaths.value.map(path => path.replaceAll('\\', '/').split('/')[0])
    return [...new Set(names)]
  })
  const resolutionRows = computed(() => {
    const result = validationResult.value || {}
    return [
      ...(result.suggested || []).map(item => ({
        kind: 'suggested',
        tagName: item.tag_name,
        options: item.alternatives || [],
        score: item.recommended?.score || 0,
      })),
      ...(result.ambiguous || []).map(item => ({
        kind: 'ambiguous',
        tagName: item.tag_name,
        options: item.dimensions || [],
      })),
      ...(result.missing || []).map(tagName => ({
        kind: 'missing',
        tagName,
        options: [],
      })),
    ]
  })
  const creatableDimensions = computed(() => (
    (dimensions.value || []).filter(dim => dim.is_visible !== 0 && !dim.is_managed)
  ))

  function stopPolling() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  function reset() {
    stopPolling()
    step.value = 'input'
    selectedEntries.value = []
    serverPath.value = ''
    sourceMode.value = 'browser'
    includeFilenameTags.value = false
    isDragging.value = false
    validationResult.value = null
    previewData.value = null
    uploadReport.value = null
    tagMapping.value = {}
    autoCreateTags.value = {}
    updateDuplicates.value = true
    jobId.value = null
    uploadProgress.value = null
    pollError.value = ''
    pollFailures = 0
    fatalMessage.value = ''
    permission.value = { permission_group: 'all', allow_preview: 1, allow_download: 1 }
    Object.keys(resolutions).forEach(key => delete resolutions[key])
  }

  function open() {
    reset()
    visible.value = true
  }

  function close() {
    visible.value = false
  }

  function useSelectedEntries(entries) {
    const supported = entries.filter(item => SUPPORTED_EXTENSIONS.has(extensionOf(item.file.name)))
    const oversized = supported.find(item => item.file.size > 500 * 1024 * 1024)
    if (oversized) {
      ElMessage.error(`${oversized.file.name} 超过 500MB 限制`)
      return
    }
    if (supported.length > 2000) {
      ElMessage.error('单次最多上传 2000 个文件')
      return
    }
    const totalSize = supported.reduce((total, item) => total + item.file.size, 0)
    if (totalSize > 20 * 1024 * 1024 * 1024) {
      ElMessage.error('单次文件夹上传总大小不能超过 20GB')
      return
    }
    selectedEntries.value = supported.sort((a, b) => a.relativePath.localeCompare(b.relativePath))
    sourceMode.value = 'browser'
    if (!supported.length) {
      ElMessage.warning('文件夹中没有支持的图片或视频')
    }
  }

  function onFolderInput(event) {
    const entries = [...(event.target.files || [])].map(file => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
    }))
    useSelectedEntries(entries)
    event.target.value = ''
  }

  async function onDrop(event) {
    isDragging.value = false
    const items = [...(event.dataTransfer?.items || [])]
    const entries = items
      .map(item => item.getAsEntry?.() || item.webkitGetAsEntry?.())
      .filter(Boolean)
    try {
      if (entries.length) {
        useSelectedEntries((await Promise.all(entries.map(entry => flattenEntry(entry)))).flat())
        return
      }
      useSelectedEntries([...(event.dataTransfer?.files || [])].map(file => ({
        file,
        relativePath: file.webkitRelativePath || file.name,
      })))
    } catch (error) {
      console.warn('读取拖放文件夹失败:', error)
      ElMessage.error('无法读取该文件夹，请改用“选择文件夹”')
    }
  }

  function initializeResolutions(result) {
    Object.keys(resolutions).forEach(key => delete resolutions[key])
    for (const item of result.suggested || []) {
      resolutions[item.tag_name] = {
        mode: 'existing',
        selectedId: item.recommended?.tag_value_id,
        dimensionId: item.recommended?.dimension_id,
      }
    }
    for (const item of result.ambiguous || []) {
      resolutions[item.tag_name] = { mode: 'existing', selectedId: null, dimensionId: null }
    }
    for (const tagName of result.missing || []) {
      resolutions[tagName] = {
        mode: canAutoCreate.value ? 'create' : null,
        selectedId: null,
        dimensionId: null,
      }
    }
  }

  function sourcePayload() {
    return sourceMode.value === 'browser'
      ? { relativePaths: relativePaths.value }
      : { folderPath: serverPath.value.trim() }
  }

  async function generatePreview(mapping) {
    const response = await previewFolderUpload({
      ...sourcePayload(),
      tagMapping: mapping,
      includeFilenameTags: includeFilenameTags.value,
    })
    previewData.value = response.data || {}
    step.value = 'preview'
  }

  async function startValidation() {
    if (sourceMode.value === 'browser' && !selectedEntries.value.length) {
      ElMessage.warning('请选择或拖入一个文件夹')
      return
    }
    if (sourceMode.value === 'server' && !serverPath.value.trim()) {
      ElMessage.warning('请输入服务器文件夹路径')
      return
    }

    step.value = 'validating'
    fatalMessage.value = ''
    autoCreateTags.value = {}
    tagMapping.value = {}
    try {
      const response = await validateFolderUpload({
        ...sourcePayload(),
        includeFilenameTags: includeFilenameTags.value,
      })
      const result = response.data || {}
      validationResult.value = result
      if (result.message) {
        fatalMessage.value = result.message
        step.value = 'resolution'
        return
      }

      const mapping = {}
      for (const match of result.matched || []) {
        mapping[match.tag_name] = {
          dimension_id: match.dimension_id,
          tag_value_id: match.tag_value_id,
          dimension_name: match.dimension_label || match.dimension_name,
          original_value: match.original_value,
        }
      }
      tagMapping.value = mapping
      initializeResolutions(result)
      if (result.is_valid) {
        await generatePreview(mapping)
      } else {
        step.value = 'resolution'
      }
    } catch (error) {
      console.warn('文件夹校验失败:', error)
      step.value = 'input'
    }
  }

  function optionFor(row, selectedId) {
    return row.options.find(option => option.tag_value_id === selectedId)
  }

  async function confirmResolutions() {
    const mapping = { ...tagMapping.value }
    const creates = {}
    for (const row of resolutionRows.value) {
      const resolution = resolutions[row.tagName]
      if (resolution.mode === 'existing') {
        const option = optionFor(row, resolution.selectedId)
        if (!option) {
          ElMessage.warning(`请为“${row.tagName}”选择匹配标签`)
          return
        }
        mapping[row.tagName] = {
          dimension_id: option.dimension_id,
          tag_value_id: option.tag_value_id,
          dimension_name: option.dimension_label || option.dimension_name,
          original_value: option.original_value,
        }
      } else {
        if (!canAutoCreate.value) {
          ElMessage.warning(`“${row.tagName}”没有可用匹配，请联系素材管理员创建标签`)
          return
        }
        if (row.tagName.length > 128) {
          ElMessage.warning(`“${row.tagName.slice(0, 20)}…”超过 128 个字符，不能创建为标签`)
          return
        }
        if (!resolution.dimensionId) {
          ElMessage.warning(`请选择“${row.tagName}”要创建到哪个维度`)
          return
        }
        const dim = creatableDimensions.value.find(item => item.id === resolution.dimensionId)
        mapping[row.tagName] = {
          dimension_id: resolution.dimensionId,
          tag_value_id: 0,
          dimension_name: dim?.label || '',
          original_value: row.tagName,
        }
        creates[row.tagName] = resolution.dimensionId
      }
    }
    tagMapping.value = mapping
    autoCreateTags.value = creates
    step.value = 'validating'
    try {
      await generatePreview(mapping)
    } catch (error) {
      console.warn('文件夹预览失败:', error)
      step.value = 'resolution'
    }
  }

  function startPolling(id) {
    stopPolling()
    pollFailures = 0
    pollError.value = ''
    step.value = 'executing'

    const pollOnce = async () => {
      try {
        const response = await getFolderUploadStatus(id)
        pollFailures = 0
        const job = response.data || {}
        if (job.status === 'completed') {
          stopPolling()
          uploadReport.value = job.report || {}
          step.value = 'report'
          onUploaded?.()
          return
        } else if (job.status === 'failed') {
          stopPolling()
          ElMessage.error(`后台处理失败：${job.error || '未知错误'}`)
          step.value = 'preview'
          return
        }
      } catch (error) {
        console.warn('轮询文件夹上传状态失败:', error)
        pollFailures += 1
        if (pollFailures >= 3) {
          stopPolling()
          pollError.value = '连续 3 次无法查询后台任务。任务可能仍在运行，你可以重新连接或先关闭弹窗。'
          step.value = 'poll_error'
          return
        }
      }
      pollTimer = setTimeout(pollOnce, 2000)
    }
    pollOnce()
  }

  function retryPolling() {
    if (jobId.value) startPolling(jobId.value)
  }

  async function confirmUpload() {
    step.value = 'executing'
    uploadProgress.value = null
    const common = {
      tagMapping: tagMapping.value,
      permission: permission.value,
      extraTags: [],
      updateDuplicates: updateDuplicates.value,
      includeFilenameTags: includeFilenameTags.value,
      autoCreateTags: autoCreateTags.value,
    }
    try {
      const response = sourceMode.value === 'browser'
        ? await uploadFolderDirect({
            ...common,
            files: selectedFiles.value,
            relativePaths: relativePaths.value,
            onProgress: progress => { uploadProgress.value = progress },
          })
        : await executeFolderUpload({ ...common, folderPath: serverPath.value.trim() })
      const data = response.data || {}
      if (data.async) {
        jobId.value = data.job_id
        startPolling(data.job_id)
      } else {
        uploadReport.value = data.report || {}
        step.value = 'report'
        onUploaded?.()
      }
    } catch (error) {
      console.warn('文件夹上传失败:', error)
      step.value = 'preview'
    }
  }

  onBeforeUnmount(stopPolling)

  return {
    visible, step, selectedEntries, serverPath, sourceMode, includeFilenameTags,
    isDragging, validationResult, previewData, uploadReport, resolutions,
    updateDuplicates, jobId, fatalMessage, permission, selectedSize, rootNames,
    uploadProgress, pollError, resolutionRows, creatableDimensions,
    open, close, reset, onFolderInput,
    onDrop, startValidation, confirmResolutions, confirmUpload,
    retryPolling,
  }
}
