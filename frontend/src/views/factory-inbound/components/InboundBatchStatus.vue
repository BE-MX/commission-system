<template>
  <section v-if="items.length || canAdvance || readError" class="batch-status">
    <header>
      <h3>入库批次</h3>
      <GlassButton variant="link" :disabled="loading || Boolean(resuming)" @click="refreshStatus">刷新进度</GlassButton>
    </header>
    <p v-if="readError" role="alert">{{ readError }}</p>
    <p v-else-if="!items.length">暂无已提交批次</p>
    <article v-for="batch in items" :key="batch.id">
      <p>
        <strong>{{ batch.batch_no }}</strong>
        <el-tag effect="plain" :type="tone(batch)">{{ label(batch) }}</el-tag>
      </p>
      <p v-if="stageLabels[batch.stage] && batch.can_resume">当前步骤 · {{ stageLabels[batch.stage] }}</p>
      <p v-if="batch.purchase_order_no">采购核对编号 {{ batch.purchase_order_no }}</p>
      <p v-if="batch.xiaoman_serial_id">入库核对编号 {{ batch.xiaoman_serial_id }}</p>
      <p v-if="batch.message" role="status">{{ batch.message }}</p>
      <GlassButton v-if="canAdvance && batch.can_resume"
        v-any-permission="['factory_inbound:write', 'factory_inbound:admin']"
        :loading="resuming === batch.id" :disabled="loading || resuming !== null"
        @click="resume(batch.id)">核对并续办</GlassButton>
      <p v-if="resuming === batch.id" role="status">正在核对原单和可继续的步骤…</p>
    </article>
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { factoryInboundApi } from '@/api/factoryInbound'
import { msgWarning } from '@/utils/feedback'

const props = defineProps({ noteId: { type: Number, required: true }, refresh: Number })
const emit = defineEmits(['batch-checked'])
const items = shallowRef([])
const canAdvance = ref(false)
const loading = ref(false)
const readError = ref('')
const resuming = ref(null)
let readRequest
let alive = true

const syncLabels = {
  confirmed: '待同步', sending: '同步中', drafted: '入库草稿', uncertain: '待核清',
  synced: '入库已完成', voided: '已作废', failed: '同步待处理', blocked: '需人工核对',
}
const stageLabels = { purchase: '采购单', draft: '入库草稿', complete: '确认入库', done: '生产单回写' }

function label(batch) {
  if (batch.sync_status === 'synced' && batch.writeback_status === 'done') return '已完成'
  if (batch.sync_status === 'synced' && batch.can_resume) return '入库已完成，待回写'
  return syncLabels[batch.sync_status] || '待核对'
}

function tone(batch) {
  if (batch.sync_status === 'synced' && !batch.can_resume) return 'success'
  if (['uncertain', 'failed', 'blocked'].includes(batch.sync_status)) return 'warning'
  return 'info'
}

async function load() {
  readRequest?.abort()
  const controller = new AbortController()
  readRequest = controller
  loading.value = true
  readError.value = ''
  try {
    const { data } = await factoryInboundApi.batches(props.noteId, {
      signal: controller.signal, suppressToast: true,
    })
    if (controller.signal.aborted) return
    items.value = data.items
    canAdvance.value = data.can_advance
  } catch {
    if (!controller.signal.aborted) {
      readError.value = '无法读取批次进度，请刷新。'
    }
  } finally {
    if (!controller.signal.aborted) loading.value = false
  }
}

async function resume(id) {
  if (resuming.value !== null || !canAdvance.value) return
  const noteId = props.noteId
  resuming.value = id
  try {
    await factoryInboundApi.resumeBatch(noteId, id, { suppressToast: true })
  } catch (error) {
    if (alive && props.noteId === noteId) {
      const detail = error.response?.data?.detail
      msgWarning(typeof detail === 'string' ? detail : '续办结果待核对，请刷新批次进度。')
    }
  } finally {
    resuming.value = null
    if (alive && props.noteId === noteId) await refreshStatus()
  }
}

async function refreshStatus() {
  const noteId = props.noteId
  await load()
  if (alive && props.noteId === noteId) emit('batch-checked')
}

watch(() => props.noteId, () => {
  items.value = []
  canAdvance.value = false
  load()
}, { immediate: true })
watch(() => props.refresh, load)
onBeforeUnmount(() => {
  alive = false
  readRequest?.abort()
})
</script>

<style scoped>
.batch-status { display: grid; gap: 8px; margin-block: 12px; }
.batch-status header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.batch-status h3, .batch-status p { margin: 0; }
.batch-status article {
  display: grid;
  justify-items: start;
  gap: 6px;
  padding: 12px;
  border: 1px solid var(--el-border-color);
  border-radius: 12px;
  overflow-wrap: anywhere;
}
.batch-status strong { margin-right: 8px; }
</style>
