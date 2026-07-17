import { computed, onMounted, ref } from 'vue'
import {
  createTask as apiCreateTask,
  deleteTask as apiDeleteTask,
  fetchMaterials,
  fetchMembers,
  fetchTasks,
  updateTask as apiUpdateTask,
} from '../api/index.js'
import { toast } from '../stores/toast.js'

export function useTasks() {
  const tasks = ref([])
  const members = ref([])
  const materialOptions = ref([])
  const loading = ref(true)
  const filters = ref({ assignee: '', phase: '' })
  const view = ref('board') // board | list

  const params = computed(() => ({
    assignee: filters.value.assignee || '',
    phase: filters.value.phase || '',
  }))

  async function load() {
    loading.value = true
    try {
      tasks.value = await fetchTasks(params.value)
    } finally {
      loading.value = false
    }
  }

  async function loadOptions() {
    // 辅助数据失败不阻断主列表（cerebrum：初始化辅助加载必须与主数据隔离）
    try {
      members.value = await fetchMembers()
    } catch { /* 拦截器已提示 */ }
    try {
      materialOptions.value = (await fetchMaterials()) || []
    } catch { /* 拦截器已提示 */ }
  }

  onMounted(() => {
    load()
    loadOptions()
  })

  async function save(id, payload) {
    if (id) {
      await apiUpdateTask(id, payload)
      toast.success('任务已保存')
    } else {
      await apiCreateTask(payload)
      toast.success('任务已创建')
    }
    await load()
  }

  async function changeStatus(task, status, blockedReason) {
    const payload = { status }
    if (status === 'blocked') payload.blocked_reason = blockedReason
    await apiUpdateTask(task.id, payload)
    toast.success(`已流转到「${{ todo: '待办', in_progress: '进行中', done: '已完成', blocked: '受阻' }[status]}」`)
    await load()
  }

  async function remove(task) {
    await apiDeleteTask(task.id)
    toast.success('任务已删除')
    await load()
  }

  return { tasks, members, materialOptions, loading, filters, view, load, save, changeStatus, remove }
}
