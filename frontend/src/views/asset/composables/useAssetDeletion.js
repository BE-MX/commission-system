import { batchDeleteAssets, deleteAsset } from '@/api/asset'

export function useAssetDeletion({ selectedAssets, previewAsset, previewVisible, loadData, clearSelection, confirm, notify }) {
  async function handleDelete(asset) {
    if (!asset) return
    try {
      await confirm(
        `确定删除「${asset.file_name}」吗？文件将被一并删除，不可恢复。`,
        '删除素材',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    try {
      await deleteAsset(asset.id)
      notify('success', '已删除')
      selectedAssets.value = selectedAssets.value.filter(item => item.id !== asset.id)
      if (previewAsset.value?.id === asset.id) previewVisible.value = false
      await loadData()
    } catch {
      // API 拦截器负责显示后端错误。
    }
  }

  async function handleBatchDelete() {
    if (!selectedAssets.value.length) return
    const count = selectedAssets.value.length
    try {
      await confirm(
        `确定删除选中的 ${count} 个素材吗？文件将被一并删除，不可恢复。`,
        '批量删除',
        { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
      )
    } catch {
      return
    }
    try {
      const res = await batchDeleteAssets(selectedAssets.value.map(item => item.id))
      const data = res.data || {}
      if (data.failed_ids?.length) {
        notify('warning', `已删除 ${data.deleted} 个，${data.failed_ids.length} 个失败`)
      } else {
        notify('success', `已删除 ${data.deleted ?? count} 个素材`)
      }
      clearSelection()
      await loadData()
    } catch {
      // API 拦截器负责显示后端错误。
    }
  }

  return { handleDelete, handleBatchDelete }
}
