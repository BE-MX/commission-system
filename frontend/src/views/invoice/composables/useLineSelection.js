import { computed, nextTick, shallowRef, triggerRef, watch } from 'vue'

/**
 * 明细表跨页勾选：el-table 只认当前页数据，翻页后勾选会被丢掉；
 * 这里按行引用自管一份选中集合，翻页/排序后把当前页的勾选状态重新灌回表格。
 * 行没有稳定 id（新增行 id=null），所以不用 row-key + reserve-selection。
 */
export function useLineSelection(tableRef, items, pagedItems) {
  const selected = shallowRef(new Set())
  const selectedCount = computed(() => selected.value.size)

  function onSelect(_selection, row) {
    if (selected.value.has(row)) selected.value.delete(row)
    else selected.value.add(row)
    triggerRef(selected)
  }
  // 表头全选只作用于当前页：全选为空时表示取消当前页
  function onSelectAll(selection) {
    const checkAll = selection.length > 0
    for (const row of pagedItems.value) {
      if (checkAll) selected.value.add(row)
      else selected.value.delete(row)
    }
    triggerRef(selected)
  }
  function clearSelection() {
    selected.value = new Set()
  }
  function takeSelected() {
    const rows = [...selected.value]
    clearSelection()
    return rows
  }

  async function syncTableSelection() {
    await nextTick()
    const table = tableRef.value
    if (!table) return
    for (const row of pagedItems.value) table.toggleRowSelection(row, selected.value.has(row))
  }
  watch(pagedItems, syncTableSelection, { flush: 'post' })
  // 行被删除/整单重载后，集合里不能留下已不在表里的引用。
  // 必须看数组本身而不是长度：保存草稿、切换发票会换一批同样行数的新行对象
  watch(items, () => {
    const alive = new Set(items.value)
    let changed = false
    for (const row of selected.value) {
      if (!alive.has(row)) { selected.value.delete(row); changed = true }
    }
    if (changed) triggerRef(selected)
  })

  return { selected, selectedCount, onSelect, onSelectAll, clearSelection, takeSelected }
}
