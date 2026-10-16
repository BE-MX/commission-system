import { ref } from 'vue'
import { createCustomerTagValue } from '@/api/customerMedia'
import { confirmAction, isFeedbackCancelled, msgError, msgWarning } from '@/utils/feedback'
import { collectDroppedFiles, dropHasDirectory, webkitPathSegments } from '../droppedFiles'
import { queueFolderFiles } from '../folderUploadTags'

const ACCEPT_RE = /\.(jpe?g|png|webp|gif|mp4|mov|webm)$/i

export function useCustomerMediaFolderUpload({
  getContext, getCustomerTags, getTagDimensions, getSelectedTags,
  selectFolderTag, onTagCreated, refreshTags, addFiles, isBlocked,
}) {
  const preparingFolders = ref(false)
  const blocked = () => isBlocked() || preparingFolders.value

  function filterAccepted(files) {
    const accepted = files.filter(({ file }) => ACCEPT_RE.test(file.name))
    const skipped = files.length - accepted.length
    if (skipped) msgWarning(`已忽略 ${skipped} 个不支持的文件`)
    return accepted
  }

  async function confirmCreate(name) {
    try {
      await confirmAction(`发现新标签，是否自动创建并选中？\n标签名称：${name}`, '发现新标签', {
        type: 'info', confirmButtonText: '创建并选中', cancelButtonText: '取消',
        closeOnClickModal: false,
      })
      return true
    } catch (error) {
      if (isFeedbackCancelled(error)) return false
      throw error
    }
  }

  async function createTag(name) {
    const dimensions = getTagDimensions().filter(dim => !dim.is_managed)
    const dimension = dimensions.find(dim => dim.name === 'customer_general')
      || (dimensions.length === 1 ? dimensions[0] : null)
    if (!dimension) throw new Error('未找到可用的客户标签维度，请先在标签维度管理中配置「客户标签」')
    const { data } = await createCustomerTagValue(getContext(), dimension.id, name)
    onTagCreated({ dimension_id: dimension.id, value: data })
    return getCustomerTags().find(tag => tag.tag_value_id === data.id)
  }

  async function prepareFiles(readFiles) {
    if (blocked()) return
    preparingFolders.value = true
    try {
      // Start reading synchronously while DataTransfer entries are still accessible.
      const files = filterAccepted(await readFiles())
      if (!files.length) return
      await refreshTags()
      await queueFolderFiles(files, {
        getCustomerTags, getSelectedTags, selectFolderTag, confirmCreate, createTag, addFiles,
      })
    } catch (error) {
      msgError(`添加文件夹失败：${error.message || '请重试'}`, error)
    } finally { preparingFolders.value = false }
  }

  function queueFile(uploadFile) {
    if (blocked()) return
    addFiles(filterAccepted([{ file: uploadFile.raw, pathSegments: [] }]))
  }

  async function onDropFolders(event) {
    if (!dropHasDirectory(event.dataTransfer)) return
    event.preventDefault()
    event.stopPropagation()
    await prepareFiles(async () => (await collectDroppedFiles(event.dataTransfer)).files)
  }

  async function onFolderSelected(event) {
    const files = [...event.target.files]
    event.target.value = ''
    await prepareFiles(() => files.map(file => ({ file, pathSegments: webkitPathSegments(file) })))
  }

  return { preparingFolders, queueFile, onDropFolders, onFolderSelected }
}
