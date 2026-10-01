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
  const tree = ref([])
  const modules = ref([])
  const stats = ref({ in_progress: 0, pending_confirm: 0, p0_open: 0, overdue: 0 })
  const brief = ref(null)
  const trash = ref([])
  const loading = ref(false)
  const briefLoading = ref(false)
  const version = ref(0)
  const today = ref(currentBeijingDate())
  const view = ref(readView())
  const filters = reactive({ q: '', moduleKey: '', priorities: [], hideClosed: true })

  watch(view, value => {
    try { localStorage.setItem(VIEW_KEY, value) } catch { /* 隐私模式不记忆，不影响使用 */ }
  })

  const modulesByKey = computed(() => Object.fromEntries(modules.value.map(m => [m.key, m])))
  const filteredTree = computed(() => filterTree(tree.value, filters))
  const columns = computed(() => boardColumns(tree.value, filters))
  const heat = computed(() => moduleHeat(tree.value, modules.value))
  const parentTitleMap = computed(() => parentTitles(tree.value))

  async function refresh() {
    loading.value = true
    try {
      const [t, s] = await Promise.all([listTasks(), getTaskStats()])
      tree.value = t.data
      stats.value = s.data
      today.value = currentBeijingDate()
      version.value += 1
    } finally {
      loading.value = false
    }
  }

  async function loadModules() {
    modules.value = (await listTaskModules()).data
  }

  async function loadBrief() {
    briefLoading.value = true
    try {
      brief.value = (await getTodayBrief()).data
    } catch {
      brief.value = null
    } finally {
      briefLoading.value = false
    }
  }

  async function loadAll() {
    await Promise.all([refresh(), loadModules(), loadBrief()])
  }

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
      msgError(errorMessage(err))
      return
    }
    msgSuccess(`T-${task.id} 改为「${STATUS_META[to].label}」`)
    await refresh()
  }

  async function loadTrash() {
    trash.value = (await listTrash()).data
  }

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
    modulesByKey, filteredTree, columns, heat, parentTitleMap,
    refresh, loadAll, loadBrief, setStatus, loadTrash, restore, togglePriority, addCustom, removeCustom,
  }
}
