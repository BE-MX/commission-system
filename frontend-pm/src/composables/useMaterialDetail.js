import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import {
  deleteMaterial as apiDeleteMaterial,
  deleteVersion as apiDeleteVersion,
  fetchFileLink,
  fetchMaterial,
  fetchMembers,
  retryDiff as apiRetryDiff,
  updateMaterial as apiUpdateMaterial,
  uploadVersion as apiUploadVersion,
} from '../api/index.js'
import { toast } from '../stores/toast.js'

const POLL_INTERVAL = 3000
const POLL_MAX = 60 // 3 分钟封顶，防忘了关页面空转

export function useMaterialDetail() {
  const route = useRoute()
  const id = Number(route.params.id)
  const material = ref(null)
  const members = ref([])
  const loading = ref(true)
  const notFound = ref(false)

  let pollTimer = null
  let pollCount = 0

  async function load(silent = false) {
    if (!silent) loading.value = true
    try {
      material.value = await fetchMaterial(id)
      notFound.value = false
      schedulePoll()
    } catch (err) {
      if (err?.status === 404) notFound.value = true
    } finally {
      loading.value = false
    }
  }

  // 有 pending 的差异任务才轮询；全部落定即停（固定间隔+在途守卫由 load 串行保证）
  function schedulePoll() {
    stopPoll()
    const hasPending = material.value?.versions?.some((v) => v.diff_status === 'pending' && !v.is_deleted)
    if (!hasPending || pollCount >= POLL_MAX) return
    pollTimer = setTimeout(async () => {
      pollCount += 1
      await load(true)
    }, POLL_INTERVAL)
  }

  function stopPoll() {
    if (pollTimer) {
      clearTimeout(pollTimer)
      pollTimer = null
    }
  }

  onMounted(async () => {
    load()
    try {
      members.value = (await fetchMembers()) || []
    } catch { /* 辅助数据缺失不阻断 */ }
  })
  onBeforeUnmount(stopPoll)

  const nameOf = (username) => members.value.find((m) => m.username === username)?.display_name || username

  const canUpload = computed(() => material.value?.delivery_type === 'file')

  async function setStatus(status) {
    await apiUpdateMaterial(id, { status })
    toast.success('状态已更新')
    await load(true)
  }

  async function saveEdit(payload) {
    await apiUpdateMaterial(id, payload)
    toast.success('已保存')
    await load()
  }

  async function upload(file, changeNote) {
    const v = await apiUploadVersion(id, file, changeNote)
    toast.success(`已上传 v${v.version_no}，AI 差异概要生成中`)
    pollCount = 0
    await load()
  }

  async function removeVersion(version) {
    await apiDeleteVersion(version.id)
    toast.success(`已删除 v${version.version_no}`)
    await load()
  }

  async function retryDiff(version) {
    await apiRetryDiff(version.id)
    toast.success('已重新排队，稍候自动刷新')
    pollCount = 0
    await load(true)
  }

  async function removeMaterial() {
    await apiDeleteMaterial(id)
    toast.success('资料已删除（软删除，留痕可恢复）')
  }

  async function download(version) {
    const link = await fetchFileLink(version.id, 'attachment')
    const a = document.createElement('a')
    a.href = link.url
    a.download = link.download_name
    document.body.appendChild(a)
    a.click()
    a.remove()
  }

  return {
    id, material, members, loading, notFound,
    nameOf, canUpload, load, setStatus, saveEdit, upload, removeVersion, retryDiff, removeMaterial, download,
  }
}
