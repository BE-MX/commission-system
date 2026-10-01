/**
 * 快速建任务浮层的全局单例状态。侧栏悬浮 +、页头「记任务」、任务中心页都通过
 * openQuickTask 打开同一个浮层（QuickTaskPopover 挂在 MainLayout）。
 * seq 每次打开自增：浮层已开着时换一个入口再点，也能重新初始化。
 */
import { reactive, ref } from 'vue'

const state = reactive({ open: false, seq: 0, anchor: null, moduleKey: null, parentId: null, source: 'manual' })
const lastCreatedId = ref(0)
let returnFocusEl = null

export function useQuickTask() {
  function openQuickTask({ anchorEl = null, moduleKey = null, parentId = null, source = 'manual' } = {}) {
    const rect = anchorEl?.getBoundingClientRect?.()
    returnFocusEl = anchorEl
    Object.assign(state, {
      open: true,
      seq: state.seq + 1,
      moduleKey,
      parentId,
      source,
      anchor: rect
        ? { top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left,
            side: anchorEl.closest?.('.aside') ? 'right' : 'below' }
        : null,
    })
  }

  function closeQuickTask() {
    if (!state.open) return
    state.open = false
    returnFocusEl?.focus?.()
    returnFocusEl = null
  }

  function notifyCreated(id) {
    lastCreatedId.value = id
  }

  return { quickTask: state, lastCreatedId, openQuickTask, closeQuickTask, notifyCreated }
}
