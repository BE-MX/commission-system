import { h, ref } from 'vue'
import { ElCheckbox, ElOption, ElSelect } from 'element-plus'
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

  async function confirmCreate(names) {
    const dimensions = getTagDimensions().filter(dim => !dim.is_managed && dim.is_visible !== 0 && dim.is_visible !== false)
    if (!dimensions.length) throw new Error('没有可新建标签的客户维度，请在标签维度管理中启用一个非系统托管的客户维度')
    const defaultDimension = dimensions.find(dim => dim.name === 'customer_general')
      || (dimensions.length === 1 ? dimensions[0] : null)
    const dimensionId = ref(defaultDimension?.id ?? null)
    const shared = ref(true)
    const individual = ref(new Map())
    const multiple = names.length > 1
    const chosenId = name => shared.value ? dimensionId.value : individual.value.get(name)
    function selector(id, value, onChange) {
      return h(ElSelect, {
        modelValue: value, 'onUpdate:modelValue': onChange, 'aria-labelledby': id,
        placeholder: '请选择标签维度', style: { width: '100%' },
      }, () => dimensions.map(dim => h(ElOption, { key: dim.id, label: dim.label, value: dim.id })))
    }
    const listStyle = { maxHeight: '32vh', overflowY: 'auto', overflowWrap: 'anywhere' }
    try {
      await confirmAction(() => h('div', [
        multiple && h(ElCheckbox, {
          modelValue: shared.value, 'onUpdate:modelValue': value => {
            if (!value && !individual.value.size) {
              for (const name of names) individual.value.set(name, dimensionId.value)
            }
            shared.value = value
          },
        }, () => '所有新标签使用同一维度'),
        ...(shared.value ? [
          h('p', { style: listStyle }, `标签名称：${names.join('、')}`),
          h('p', { id: 'folder-tag-dimension-label' }, '标签维度'),
          selector('folder-tag-dimension-label', dimensionId.value, value => { dimensionId.value = value }),
        ] : [h('div', { style: listStyle }, names.map((name, index) => {
          const id = `folder-tag-dimension-${index}`
          return h('div', { key: name }, [
            h('p', { id }, name),
            selector(id, individual.value.get(name), value => { individual.value.set(name, value) }),
          ])
        }))]),
      ].filter(Boolean)), multiple ? `创建 ${names.length} 个新标签` : '发现新标签', {
        type: 'info', confirmButtonText: multiple ? '批量创建' : '创建并选中', cancelButtonText: '取消',
        closeOnClickModal: false,
        beforeClose(action, instance, done) {
          if (action === 'confirm' && names.some(name => !dimensions.some(dim => dim.id === chosenId(name)))) {
            msgWarning('请选择新标签所属的维度')
            return
          }
          done()
        },
      })
      return new Map(names.map(name => [name, dimensions.find(dim => dim.id === chosenId(name))]))
    } catch (error) {
      if (isFeedbackCancelled(error)) return null
      throw error
    }
  }

  async function createTag(name, dimension) {
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
