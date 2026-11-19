<template>
  <section v-if="items.length || canAdvance || readError" class="batch-status">
    <header>
      <h2>入库批次</h2>
      <button class="batch-link" type="button" :disabled="loading || Boolean(resuming)" @click="refreshStatus">
        {{ loading ? '正在刷新…' : '刷新进度' }}
      </button>
    </header>
    <p v-if="readError" class="batch-error" role="alert">{{ readError }}</p>
    <p v-else-if="!items.length" class="batch-empty">暂无已提交批次</p>
    <article v-for="batch in items" :key="batch.id">
      <div class="batch-top">
        <strong>{{ batch.batch_no }}</strong>
        <span class="pill" :class="'tone-' + tone(batch)">{{ label(batch) }}</span>
      </div>
      <dl>
        <div v-if="stageLabels[batch.stage] && batch.can_resume"><dt>当前步骤</dt><dd>{{ stageLabels[batch.stage] }}</dd></div>
        <div v-if="batch.purchase_order_no"><dt>采购核对编号</dt><dd>{{ batch.purchase_order_no }}</dd></div>
        <div v-if="batch.xiaoman_serial_id"><dt>入库核对编号</dt><dd>{{ batch.xiaoman_serial_id }}</dd></div>
      </dl>
      <p v-if="batch.message" class="batch-message" role="status">{{ batch.message }}</p>
      <button v-if="canAdvance && batch.can_resume"
        v-any-permission="['factory_inbound:write', 'factory_inbound:admin']" class="batch-resume" type="button"
        :disabled="loading || resuming !== null" @click="resume(batch.id)">
        {{ resuming === batch.id ? '正在续办…' : '核对并续办' }}
      </button>
      <p v-if="resuming === batch.id" class="batch-message" role="status">正在核对原单和可继续的步骤…</p>
    </article>
  </section>
</template>

<script setup>
import { onBeforeUnmount, ref, shallowRef, watch } from 'vue'
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

<style src="../pills.css" scoped></style>
<style scoped>
.batch-status { display: grid; gap: 10px; margin-top: 16px; padding: 20px; border: 1px solid var(--border-color); border-radius: 20px; background: var(--card-bg); }
.batch-status header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.batch-status h2 { margin: 0; font-size: 17px; font-weight: 750; }
.batch-link { min-height: 44px; padding: 0; border: 0; background: none; color: var(--button-primary); font: inherit; font-size: 14px; font-weight: 600; cursor: pointer; }
.batch-error, .batch-empty, .batch-message { margin: 0; font-size: 13px; line-height: 1.6; }
.batch-error { color: var(--color-danger-text); }
.batch-empty, .batch-message { color: var(--text-secondary); }
.batch-status article { display: grid; gap: 10px; padding: 14px; border-radius: 14px; background: var(--page-bg); overflow-wrap: anywhere; }
.batch-top { display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 8px; }
.batch-top strong { font-family: var(--font-mono, ui-monospace, monospace); font-size: 15px; }
dl { display: grid; gap: 6px; margin: 0; }
dl div { display: flex; justify-content: space-between; gap: 12px; font-size: 13px; }
dt { color: var(--text-secondary); }
dd { margin: 0; font-weight: 650; text-align: right; }
.batch-resume {
  min-height: 48px; border: 1px solid var(--button-primary); border-radius: 12px; background: var(--button-primary);
  color: var(--button-surface); font: inherit; font-size: 15px; font-weight: 650; cursor: pointer;
  transition: transform 140ms cubic-bezier(.23, 1, .32, 1), background-color 160ms ease;
}
.batch-resume:active:not(:disabled) { transform: scale(.97); }
.batch-resume:disabled { background: var(--button-disabled-bg); border-color: var(--button-border); color: var(--button-disabled-text); cursor: not-allowed; }
.batch-resume:focus-visible, .batch-link:focus-visible { outline: 3px solid var(--button-focus, var(--button-primary)); outline-offset: 2px; }
@media (hover: hover) and (pointer: fine) { .batch-resume:hover:not(:disabled) { background: var(--button-primary-hover); } }
@media (prefers-reduced-motion: reduce) { .batch-resume { transition: none; } .batch-resume:active { transform: none; } }
</style>
