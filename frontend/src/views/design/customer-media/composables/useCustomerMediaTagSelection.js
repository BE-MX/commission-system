import { computed, ref, watch } from 'vue'

// Locks are local to the open upload dialog. Asset queue entries keep their own snapshots.
export function useCustomerMediaTagSelection({ customerTags, tagDimensions, isBlocked, onConflict }) {
  const selectedTagIds = ref([])
  const lockedTagIds = ref([])
  const selectedTags = computed(() => customerTags.value.filter(tag => selectedTagIds.value.includes(tag.tag_value_id)))
  const lockedTags = computed(() => customerTags.value.filter(tag => lockedTagIds.value.includes(tag.tag_value_id)))

  watch(() => customerTags.value.map(tag => tag.tag_value_id), ids => {
    const available = new Set(ids)
    selectedTagIds.value = selectedTagIds.value.filter(id => available.has(id))
    lockedTagIds.value = lockedTagIds.value.filter(id => available.has(id))
  }, { flush: 'sync' })

  function lockedConflict(tag) {
    if (!tagDimensions.value.find(dim => dim.id === tag.dimension_id)?.is_single_select) return null
    return lockedTags.value.find(locked => locked.dimension_id === tag.dimension_id
      && locked.tag_value_id !== tag.tag_value_id)
  }

  function toggleTag(tag) {
    if (isBlocked()) return
    if (lockedTagIds.value.includes(tag.tag_value_id) || lockedConflict(tag)) {
      onConflict('请先取消该维度标签的锁定，再修改选择')
      return
    }
    if (selectedTagIds.value.includes(tag.tag_value_id)) {
      selectedTagIds.value = selectedTagIds.value.filter(id => id !== tag.tag_value_id)
      return
    }
    if (tagDimensions.value.find(dim => dim.id === tag.dimension_id)?.is_single_select) {
      const sameDim = new Set(customerTags.value.filter(item => item.dimension_id === tag.dimension_id)
        .map(item => item.tag_value_id))
      selectedTagIds.value = selectedTagIds.value.filter(id => !sameDim.has(id))
    }
    selectedTagIds.value = [...selectedTagIds.value, tag.tag_value_id]
  }

  function toggleTagLock(tag) {
    if (isBlocked() || !selectedTagIds.value.includes(tag.tag_value_id)) return
    lockedTagIds.value = lockedTagIds.value.includes(tag.tag_value_id)
      ? lockedTagIds.value.filter(id => id !== tag.tag_value_id)
      : [...lockedTagIds.value, tag.tag_value_id]
  }

  function selectFolderTag(tag) {
    const conflict = lockedConflict(tag)
    if (conflict) throw new Error(`标签「${tag.value}」与已锁定的「${conflict.value}」同属单选维度，请先解锁后重新添加文件夹`)
    const tags = [...lockedTags.value]
    if (!tags.some(item => item.tag_value_id === tag.tag_value_id)) tags.push(tag)
    selectedTagIds.value = tags.map(item => item.tag_value_id)
    return tags
  }

  function clearTagLocks() { lockedTagIds.value = [] }

  return { selectedTagIds, selectedTags, lockedTagIds, toggleTag, toggleTagLock, selectFolderTag, clearTagLocks }
}
