/** 任务中心页状态与动作：加载、筛选、视图切换（本机记忆）、状态变更（受阻原因 / 完成确认）、回收站、私有分类。 */
import { computed, reactive, ref, watch } from 'vue'
import {
  addCustomModule, changeTaskStatus, getTaskStats, getTodayBrief, listTaskModules, listTasks, listTrash,
  removeCustomModule, restoreTask,
} from '@/api/task'
import { currentBeijingDate } from '@/utils/datetime'
import { msgError, msgSuccess } from '@/utils/feedback'
import { STATUS_META } from '../taskLabels.js'
import { boardColumns, filterTree, moduleHeat, openDescendantCount, parentTitles } from '../taskTree.js'
import { useAsyncResource } from '@/composables/useAsyncResource'
import { useAuthStore } from '@/stores/auth'
import { useTaskDialog } from './useTaskDialog'

const VIEW_KEY = 'ark.task.view'
const VIEWS = ['tree', 'board', 'map']

function readView() {
  try {
    const saved = localStorage.getItem(VIEW_KEY)
    return VIEWS.includes(saved) ? saved : 'tree'
  } catch {
    return 'tree'
  }
}

export function errorMessage(err, fallback = '操作失败') {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  return detail?.message || err?.response?.data?.message || fallback
}

export function useTaskCenter() {
  const { ask } = useTaskDialog()
  const authStore = useAuthStore()
  const readOptions = signal => ({ signal, suppressToast: true })
  const treeResource = useAsyncResource(async (_, { signal, isCurrent }) => {
    const result = (await listTasks(readOptions(signal))).data
    if (isCurrent()) { today.value = currentBeijingDate(); version.value += 1 }
    return result
  }, { initialData: [] })
  const modulesResource = useAsyncResource(async (_, { signal }) => (await listTaskModules(readOptions(signal))).data, { initialData: [] })
  const statsResource = useAsyncResource(async (_, { signal }) => (await getTaskStats(readOptions(signal))).data)
  const briefResource = useAsyncResource(async (_, { signal }) => (await getTodayBrief(readOptions(signal))).data)
  const trashResource = useAsyncResource(async (_, { signal }) => (await listTrash(readOptions(signal))).data, { initialData: [] })
  const tree = treeResource.data, modules = modulesResource.data, trash = trashResource.data
  const stats = computed(() => statsResource.data.value || {})
  const brief = briefResource.data, loading = treeResource.loading, briefLoading = briefResource.loading
  const version = ref(0)
  const today = ref(currentBeijingDate())
  const view = ref(readView())
  const defaultFilters = () => ({ q: '', moduleKey: '', priorities: [], hideClosed: true })
  const filters = reactive(defaultFilters())
  const appliedFilters = ref(defaultFilters())
  function applyFilters() { appliedFilters.value = JSON.parse(JSON.stringify(filters)) }
  function resetFilters() { Object.assign(filters, defaultFilters()); applyFilters() }

  watch(view, value => {
    try { localStorage.setItem(VIEW_KEY, value) } catch { /* 隐私模式不记忆，不影响使用 */ }
  })

  const modulesByKey = computed(() => Object.fromEntries(modules.value.map(m => [m.key, m])))
  const filteredTree = computed(() => filterTree(tree.value, appliedFilters.value))
  const columns = computed(() => boardColumns(tree.value, appliedFilters.value))
  const heat = computed(() => moduleHeat(tree.value, modules.value))
  const parentTitleMap = computed(() => parentTitles(tree.value))

  async function refresh() { return Promise.all([treeResource.load(), statsResource.load()]) }
  function loadModules() { return modulesResource.load() }
  function loadBrief() { return briefResource.load() }
  async function loadAll() { return Promise.all([refresh(), loadModules(), loadBrief()]) }
  watch(() => authStore.user?.id, () => {
    for (const resource of [treeResource, modulesResource, statsResource, briefResource, trashResource]) resource.clear()
    resetFilters()
    void loadAll()
  })

  // 设计文档第 3 节：任何未结束任务标记完成都要人确认；有未结束子任务时文案里说明
  async function confirmDone(task) {
    const open = openDescendantCount(tree.value, task.id)
    return ask({
      title: `确认 T-${task.id} 已完成？`,
      message: open ? `${task.title}\n还有 ${open} 个子任务没结束，它们会保持原状态。` : task.title,
      confirmText: '确认完成',
    })
  }

  async function setStatus(task, to) {
    // 「待确认」只能由 AI/代理提议：抽屉不提供该选项，看板拖入直接忽略
    if (!task || task.status === to || to === 'pending_confirm') return
    const payload = { status: to }
    if (to === 'blocked') {
      const reason = await ask({
        title: `T-${task.id} 受阻原因`,
        message: '写清楚卡在哪里，方便之后跟进',
        input: true,
        placeholder: '例如：等财务给 9 月汇率口径',
        confirmText: '标记受阻',
        validate: value => (value ? '' : '受阻原因必填'),
      })
      if (!reason) return
      payload.reason = reason
    }
    if (task.status === 'pending_confirm' && to === 'in_progress') {
      const reason = await ask({
        title: `驳回 T-${task.id} 的完成提议`,
        message: '说明哪些验收项仍未完成',
        input: true,
        confirmText: '驳回并继续',
        validate: value => (value ? '' : '驳回理由必填'),
      })
      if (!reason) return
      payload.reason = reason
    }
    if (to === 'done') {
      if (!(await confirmDone(task))) return
      payload.confirm_open_children = true
    }
    try {
      await changeTaskStatus(task.id, payload)
    } catch (err) {
      msgError(errorMessage(err), err)
      return
    }
    msgSuccess(`T-${task.id} 改为「${STATUS_META[to].label}」`)
    await refresh()
  }

  function loadTrash() { return trashResource.load() }

  async function restore(item) {
    await restoreTask(item.id)
    msgSuccess(`恢复 T-${item.id} `)
    await Promise.all([refresh(), loadTrash()])
  }

  async function addCustom() {
    const title = await ask({
      title: '新建方舟外分类',
      message: '例如：家里的事、副业、学习',
      input: true,
      confirmText: '新建',
      validate: value => (value && value.length <= 100 ? '' : '分类名称需为 1~100 个字'),
    })
    if (!title) return
    await addCustomModule(title)
    msgSuccess(`新建分类「${title}」`)
    await loadModules()
  }

  async function removeCustom(module) {
    const ok = await ask({
      title: `停用分类「${module.title}」？`,
      message: '已关联的任务保留原分类，只是不能再选它。',
      confirmText: '停用',
    })
    if (!ok) return
    await removeCustomModule(module.key)
    await loadModules()
  }

  function togglePriority(p) {
    const i = filters.priorities.indexOf(p)
    if (i >= 0) filters.priorities.splice(i, 1)
    else filters.priorities.push(p)
  }

  return {
    tree, modules, stats, brief, trash, loading, briefLoading, version, today, view, filters,
    modulesByKey, filteredTree, columns, heat, parentTitleMap, appliedFilters, applyFilters, resetFilters,
    treeResource, modulesResource, statsResource, briefResource, trashResource, loadModules,
    refresh, loadAll, loadBrief, setStatus, loadTrash, restore, togglePriority, addCustom, removeCustom,
  }
}
