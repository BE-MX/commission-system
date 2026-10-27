import { computed, ref } from 'vue'

import { confirmDanger, isFeedbackCancelled, msgWarning, promptAction } from '../../../utils/feedback.js'
import { currentBeijingDate } from '../../../utils/datetime.js'
import { newRequestKey } from '../../../utils/requestKey.js'

export const ALL_ITEM_GROUPS = '__all_item_groups__'

export function suggestedItemGroupName(groups, today) {
  const existing = new Set(groups.map(group => group.name))
  if (!existing.has(today)) return today
  let sequence = 2
  while (existing.has(`${today} 追加 ${sequence}`)) sequence += 1
  return `${today} 追加 ${sequence}`
}

export function itemGroupNameError(value, groups, ignoreKey = '') {
  const name = String(value || '').trim()
  if (!name) return '请输入分组名称'
  if (name.length > 64) return '分组名称不能超过 64 个字符'
  if (groups.some(group => group.key !== ignoreKey && group.name.trim().toLowerCase() === name.toLowerCase())) {
    return '同一订单内分组名称不能重复'
  }
  return ''
}

export function useInvoiceItemGroups(form, options = {}) {
  const today = options.today || currentBeijingDate
  const newKey = options.newKey || newRequestKey
  const prompt = options.prompt || promptAction
  const confirm = options.confirm || confirmDanger
  const warn = options.warn || msgWarning
  const activeGroupKey = ref(ALL_ITEM_GROUPS)
  const loadedInvoiceId = ref(null)
  const groups = computed(() => form.item_groups || [])
  const activeGroup = computed(() => groups.value.find(group => group.key === activeGroupKey.value) || null)
  const activeGroupName = computed(() => activeGroup.value?.name || '')
  const canAppendToGroup = computed(() => Boolean(activeGroup.value))
  const groupCounts = computed(() => Object.fromEntries(groups.value.map(group => [
    group.key,
    form.items.filter(row => row.product_kind !== 'accessory' && row.group_key === group.key).length,
  ])))

  function resetItemGroups(data = {}) {
    const previousKey = activeGroupKey.value
    const sameInvoice = loadedInvoiceId.value === (data.id || null)
    if (!Array.isArray(form.item_groups)) form.item_groups = []
    if (!data.id) {
      if (!form.item_groups.length) {
        form.item_groups.push({ key: newKey(), name: suggestedItemGroupName(groups.value, today()), sort_order: 1 })
      }
      const fallback = form.item_groups[0].key
      for (const row of form.items) {
        if (row.product_kind !== 'accessory' && !row.group_key) row.group_key = fallback
      }
    }
    if (sameInvoice && groups.value.some(group => group.key === previousKey)) activeGroupKey.value = previousKey
    else if (!data.id && form.item_groups.length) activeGroupKey.value = form.item_groups[0].key
    else if (data.id && form.item_groups.length) activeGroupKey.value = form.item_groups.at(-1).key
    else activeGroupKey.value = ALL_ITEM_GROUPS
    loadedInvoiceId.value = data.id || null
  }

  function getTargetGroupKey() {
    return activeGroup.value?.key || null
  }

  function getSourceItems(groupKey) {
    return form.items.filter(row => row.product_kind !== 'accessory' && row.group_key === groupKey)
  }

  async function createItemGroup() {
    const initial = suggestedItemGroupName(groups.value, today())
    let answer
    try {
      answer = await prompt('新增、复制和 Excel 粘贴将进入新分组。', '新建明细分组', {
        inputValue: initial,
        inputValidator: value => itemGroupNameError(value, groups.value) || true,
        confirmButtonText: '新建分组', cancelButtonText: '取消',
      })
    } catch (error) {
      if (isFeedbackCancelled(error)) return null
      throw error
    }
    const group = {
      key: newKey(),
      name: String(answer.value || '').trim(),
      sort_order: Math.max(0, ...groups.value.map(row => Number(row.sort_order || 0))) + 1,
    }
    form.item_groups.push(group)
    activeGroupKey.value = group.key
    return group
  }

  async function renameItemGroup(key = activeGroupKey.value) {
    const group = groups.value.find(row => row.key === key)
    if (!group) return false
    let answer
    try {
      answer = await prompt('分组名称仅用于明细查看，不影响出库或订单业务数据。', '重命名明细分组', {
        inputValue: group.name,
        inputValidator: value => itemGroupNameError(value, groups.value, key) || true,
        confirmButtonText: '保存名称', cancelButtonText: '取消',
      })
    } catch (error) {
      if (isFeedbackCancelled(error)) return false
      throw error
    }
    group.name = String(answer.value || '').trim()
    return true
  }

  async function deleteItemGroup(key = activeGroupKey.value) {
    const group = groups.value.find(row => row.key === key)
    if (!group) return false
    if (getSourceItems(key).length) {
      warn('请先移动或删除该分组中的产品明细')
      return false
    }
    try {
      await confirm('删除', `明细分组「${group.name}」`, '仅删除空标签，不删除任何订单明细。')
    } catch (error) {
      if (isFeedbackCancelled(error)) return false
      throw error
    }
    form.item_groups.splice(form.item_groups.indexOf(group), 1)
    if (activeGroupKey.value === key) activeGroupKey.value = ALL_ITEM_GROUPS
    return true
  }

  function moveRowsToGroup(rows, targetKey) {
    if (!groups.value.some(group => group.key === targetKey)) {
      warn('请选择有效的目标分组')
      return false
    }
    for (const row of rows) row.group_key = targetKey
    return true
  }

  return {
    activeGroupKey,
    activeGroup,
    activeGroupName,
    canAppendToGroup,
    groupCounts,
    resetItemGroups,
    getTargetGroupKey,
    getSourceItems,
    createItemGroup,
    renameItemGroup,
    deleteItemGroup,
    moveRowsToGroup,
  }
}
