<template>
  <div class="research-tab">
    <div class="panel status-panel">
      <div class="status-copy" aria-live="polite">
        <strong>{{ statusText }}</strong>
        <span v-if="state?.last_run_at" class="muted">上次背调 {{ formatBeijingDateTime(state.last_run_at, { seconds: false }) }}</span>
        <span v-if="remaining > 0" class="muted">冷却剩余 {{ cooldownLabel }} · {{ formatBeijingDateTime(state.cooldown_until, { seconds: false }) }} 可重跑</span>
      </div>
      <el-button
        v-permission="'client_desk:write'" type="primary"
        :loading="submitting" :disabled="!state?.can_rerun || loading || !!loadError"
        @click="rerun"
      >重新背调</el-button>
    </div>
    <el-alert v-if="loadError" type="error" :closable="false">
      {{ loadError }} <el-button link type="primary" @click="refresh">刷新状态</el-button>
    </el-alert>
    <el-alert v-if="actionError" :title="actionError" type="error" :closable="false" />
    <ResearchReport
      v-if="state || initialReport?.status === 'ready' || !loading"
      :report="state?.report ?? initialReport" show-evidence
      @evidence="$emit('evidence', $event)"
    />
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { clientDeskApi } from '@/api/clientDesk'
import { formatBeijingDateTime } from '@/utils/datetime'
import { errorMessage } from '@/utils/errors'
import ResearchReport from './ResearchReport.vue'

const props = defineProps({
  companyId: { type: [String, Number], required: true },
  initialReport: { type: Object, default: null },
})
const emit = defineEmits(['evidence', 'report'])
const state = ref(null)
const loading = ref(true)
const submitting = ref(false)
const loadError = ref('')
const actionError = ref('')
const remaining = ref(0)
let cooldownEnd = 0
let active = true
let controller
let pollTimer
let clockTimer

const labels = {
  unavailable: '当前客户暂不可背调',
  idle: '尚未发起背调',
  pending: '背调已排队',
  running: '背调进行中',
  completed: '上次背调已完成',
  failed: '上次背调失败',
  skipped: '上次背调已跳过',
  cancelled: '上次背调已取消',
}
const statusText = computed(() => {
  if (loading.value && !state.value) return '正在读取背调状态…'
  if (!state.value) return '背调状态暂不可用'
  return labels[state.value.status] || '背调状态暂不可用'
})
const cooldownLabel = computed(() => {
  const seconds = remaining.value
  const days = Math.floor(seconds / 86400)
  const hours = Math.floor(seconds / 3600) % 24
  if (days) return `${days} 天 ${hours} 小时`
  const minutes = Math.ceil(seconds / 60)
  if (hours) return `${hours} 小时 ${Math.floor(seconds / 60) % 60} 分钟`
  return minutes > 1 ? `${minutes} 分钟` : `${seconds} 秒`
})

function setState(data) {
  state.value = data
  if (data.report) emit('report', data.report)
  remaining.value = data.cooldown_remaining_seconds || 0
  cooldownEnd = Date.now() + remaining.value * 1000
}

function schedulePoll() {
  clearTimeout(pollTimer)
  if (active && !loadError.value && ['pending', 'running'].includes(state.value?.status)) {
    pollTimer = setTimeout(refresh, 15000)
  }
}

async function refresh() {
  clearTimeout(pollTimer)
  controller?.abort()
  const request = new AbortController()
  controller = request
  loading.value = true
  loadError.value = ''
  try {
    const data = await clientDeskApi.research(props.companyId, request.signal)
    if (active && !request.signal.aborted) setState(data)
  } catch (error) {
    if (active && !request.signal.aborted) {
      loadError.value = errorMessage(error, '读取背调状态失败')
      if ([403, 404].includes(error?.response?.status)) {
        state.value = null
        emit('report', { status: 'none' })
      }
    }
  } finally {
    if (active && !request.signal.aborted) {
      loading.value = false
      schedulePoll()
    }
  }
}

async function rerun() {
  if (submitting.value || !state.value?.can_rerun) return
  clearTimeout(pollTimer)
  submitting.value = true
  actionError.value = ''
  try {
    const data = await clientDeskApi.rerunResearch(props.companyId)
    if (active) setState(data)
  } catch (error) {
    if (active) {
      actionError.value = errorMessage(error, '提交背调失败')
      await refresh()
    }
  } finally {
    if (active) {
      submitting.value = false
      schedulePoll()
    }
  }
}

onMounted(() => {
  refresh()
  clockTimer = setInterval(() => {
    if (!remaining.value) return
    remaining.value = Math.max(0, Math.ceil((cooldownEnd - Date.now()) / 1000))
    if (!remaining.value && !loading.value && !submitting.value) refresh()
  }, 1000)
})
onBeforeUnmount(() => {
  active = false
  controller?.abort()
  clearTimeout(pollTimer)
  clearInterval(clockTimer)
})
</script>

<style src="./board.css" scoped></style>
<style scoped>
.research-tab { display: grid; gap: 12px; }
.status-panel { display: flex; align-items: center; justify-content: space-between; gap: 10px; flex-wrap: wrap; }
.status-copy { display: grid; gap: 4px; }
</style>
