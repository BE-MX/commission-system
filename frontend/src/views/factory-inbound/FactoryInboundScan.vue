<template>
  <main class="factory-scan">
    <header class="scan-head">
      <GlassButton v-if="noteId || scanning" variant="link" :disabled="uploading" @click="goDrafts">返回草稿</GlassButton>
      <GlassButton v-else variant="link" @click="router.push('/dashboard')">工作台</GlassButton>
      <h1>工厂到货拍照</h1>
      <span aria-hidden="true"></span>
    </header>

    <div v-if="initError" class="work-card" role="alert">
      <p>{{ initError }}</p><GlassButton @click="initialize">重试</GlassButton>
    </div>
    <div v-else-if="!settings" class="work-card"><el-skeleton :rows="2" /></div>
    <template v-else-if="scanning">
      <DocumentScanner v-if="!uploading" finish="emit" finish-label="识别这张" default-effect="enhanced"
        :max-upload-bytes="settings.max_upload_bytes" @captured="submitCapture" @cancel="goDrafts" />
      <div v-else class="work-card" role="status"><el-skeleton :rows="3" /><p>正在上传照片…</p></div>
    </template>

    <section v-else-if="!noteId" class="drafts">
      <div class="work-card new-note">
        <GlassButton class="capture-entry" variant="primary" :icon="Camera" full-width :disabled="uploading" @click="scanning = true">拍新单</GlassButton>
        <div v-if="savedCapture" class="resume">
          <GlassButton variant="link" :disabled="uploading" @click="submitCapture(savedCapture)">继续上传上次的照片</GlassButton>
          <GlassButton variant="link" :disabled="uploading" @click="discardCapture">清除暂存照片</GlassButton>
        </div>
        <p v-if="uploadError" role="alert">{{ uploadError }}</p>
      </div>
      <h2>我的草稿</h2>
      <div v-if="draftError" class="work-card" role="alert">
        <p>无法读取草稿</p><GlassButton @click="loadDrafts">重试</GlassButton>
      </div>
      <el-skeleton v-else-if="loadingDrafts" :rows="3" />
      <p v-else-if="!drafts.length" class="muted">暂无草稿</p>
      <button v-for="draft in drafts" :key="draft.id" class="draft-card" type="button" :disabled="uploading" @click="goNote(draft.id)">
        <span><strong>{{ draft.inbound_no }}</strong><small>{{ draft.delivery_no || draft.recognized_delivery_no || '单据编号待确认' }}</small></span>
        <el-tag effect="plain">{{ noteStatus(draft) }}</el-tag>
      </button>
      <GlassButton v-if="drafts.length < draftTotal" :disabled="loadingDrafts" @click="loadDrafts(true)">加载更多</GlassButton>
    </section>

    <section v-else-if="readError" class="work-card" role="alert">
      <p>{{ readError }}</p><GlassButton @click="open(noteId)">重新读取</GlassButton>
    </section>
    <div v-else-if="!note" class="work-card"><el-skeleton :rows="4" /></div>
    <template v-else>
      <section class="work-card note-head">
        <div>
          <h2>{{ note.inbound_no }}</h2>
          <p>{{ deliveryDate(note) }} · {{ noteStatus(note) }}</p>
          <p v-if="note.delivery_no">工厂单据 {{ note.delivery_no }}</p>
          <p v-else-if="note.recognized_delivery_no">识别编号 {{ note.recognized_delivery_no }}</p>
        </div>
        <InboundPhoto :note="note" />
      </section>
      <InboundBatchStatus :note-id="note.id" :refresh="batchRefresh" @batch-checked="open(note.id, { clear: false })" />
      <section v-if="pendingRecognition(note)" class="work-card" role="status">
        <el-skeleton :rows="4" />
        <p>{{ delayed ? '识别仍在进行，可稍后从我的草稿继续。' : '识别约需 20–60 秒，可以先离开。' }}</p>
        <GlassButton v-if="delayed" @click="open(noteId, { clear: false })">刷新识别状态</GlassButton>
      </section>
      <section v-else-if="note.status === 'draft'" class="review">
        <div v-if="note.duplicate" class="work-card duplicate">
          <h2>疑似重拍</h2>
          <p>{{ note.duplicate.inbound_no }} · {{ note.duplicate.creator || '操作人未登记' }}</p>
          <div class="review-actions">
            <InboundPhoto v-if="note.duplicate.id" :note="note.duplicate" />
            <GlassButton v-if="note.duplicate.id" variant="link" @click="goNote(note.duplicate.id)">打开原草稿</GlassButton>
            <span v-else class="muted">请联系创建人或管理员核对原单</span>
            <GlassButton v-if="note.editable" variant="link" link-tone="danger" :disabled="busy" @click="voidCurrent(true)">同一张，作废本草稿</GlassButton>
          </div>
        </div>
        <div v-if="note.recognition_error" class="work-card" role="alert">{{ note.recognition_error }}</div>
        <div v-if="note.editable" class="work-card review-actions">
          <GlassButton v-if="!hasSubmittedLines && note.recognition_status === 'done'" :disabled="busy" @click="confirmNumber">
            {{ note.delivery_no || note.duplicate ? '更正单据编号' : '确认单据编号' }}
          </GlassButton>
          <GlassButton v-if="!hasSubmittedLines" variant="link" :disabled="busy" @click="retry(false)">重新识别</GlassButton>
          <GlassButton v-if="!hasSubmittedLines && note.has_original" variant="link" :disabled="busy" @click="retry(true)">用原图识别</GlassButton>
          <GlassButton v-if="note.recognition_status === 'failed'" variant="link" :disabled="busy" @click="scanning = true">重拍</GlassButton>
          <GlassButton variant="link" :disabled="busy" @click="editLine(null)">手工录入</GlassButton>
          <GlassButton v-if="!hasSubmittedLines" variant="link" link-tone="danger" :disabled="busy" @click="voidCurrent(false)">作废</GlassButton>
        </div>
        <section v-for="group in groups" :key="group.ref" class="review-group">
          <h2>{{ /^\d/.test(group.ref) ? '单号 ' + group.ref : group.ref }}</h2>
          <InboundReviewLine v-for="line in group.items" :key="line.id" :line="line" :editable="note.editable" :busy="busy"
            @change="changeLine(line.id, $event)" @edit="editLine(line)" @choose="candidateId = line.id" />
        </section>
        <footer v-if="note.lines.length" class="scan-foot">
          <span>已勾选 <strong>{{ selected.length }}</strong> 行 · 合计 {{ selectedQuantity }} 件</span>
          <GlassButton variant="primary" :disabled="!selected.length" @click="summary = true">核对汇总</GlassButton>
        </footer>
        <CandidateSheet :line="candidate" :busy="busy" @close="candidateId = null" @edit="editCandidate"
          @select="choose" />
        <LineEditDialog :open="editor" :line="editing" :types="settings.line_types" :busy="busy"
          @close="editor = false" @save="saveLine" />
        <InboundSummarySheet :note="note" :open="summary" :sync-enabled="settings.sync_enabled"
          @close="summary = false" @batch-checked="refreshBatch" />
      </section>
    </template>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Camera } from '@element-plus/icons-vue'
import GlassButton from '@/components/GlassButton.vue'
import DocumentScanner from '@/components/document-scanner/DocumentScanner.vue'
import { factoryInboundApi } from '@/api/factoryInbound'
import { useAuthStore } from '@/stores/auth'
import { confirmAction, confirmDanger, msgWarning, promptAction } from '@/utils/feedback'
import CandidateSheet from './components/CandidateSheet.vue'
import InboundBatchStatus from './components/InboundBatchStatus.vue'
import InboundPhoto from './components/InboundPhoto.vue'
import InboundReviewLine from './components/InboundReviewLine.vue'
import InboundSummarySheet from './components/InboundSummarySheet.vue'
import LineEditDialog from './components/LineEditDialog.vue'
import { clearCapture, loadCapture, storeCapture } from './composables/pendingCapture'
import { useInboundRecognition } from './composables/useInboundRecognition'
import { deliveryDate, groupLines, noteStatus, pendingRecognition } from './inboundLabels'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const actor = computed(() => auth.user?.id)
const { note, delayed, readError, open, cancel } = useInboundRecognition()
const noteId = computed(() => /^\d+$/.test(String(route.query.note || '')) ? Number(route.query.note) : null)
const settings = shallowRef(null)
const initError = ref('')
const scanning = ref(false)
const uploading = ref(false)
const uploadError = ref('')
const savedCapture = shallowRef(null)
const drafts = shallowRef([])
const draftTotal = ref(0)
const draftError = ref(false)
const loadingDrafts = ref(false)
const busy = ref(false)
const batchRefresh = ref(0)
const candidateId = ref(null)
const summary = ref(false)
const editor = ref(false)
const editing = shallowRef(null)
const candidate = computed(() => note.value?.lines.find(line => line.id === candidateId.value))
const groups = computed(() => groupLines(note.value?.lines || []))
const selected = computed(() => note.value?.lines.filter(line => !line.batch_id && line.selected && line.match_status === 'matched') || [])
const hasSubmittedLines = computed(() => note.value?.lines.some(line => line.batch_id))
const selectedQuantity = computed(() => selected.value.reduce((sum, line) => sum + line.values.quantity, 0))
let uploadRequest
let draftRequest
let draftPage = 1
let alive = true

async function initialize() {
  initError.value = ''
  try {
    settings.value = (await factoryInboundApi.settings({ suppressToast: true })).data
    savedCapture.value = await loadCapture(actor.value)
  } catch (error) {
    initError.value = error.response?.data?.detail || '无法加载工厂到货功能'
  }
}

async function loadDrafts(more = false) {
  draftRequest?.abort()
  const controller = new AbortController()
  draftRequest = controller
  loadingDrafts.value = true
  draftError.value = false
  try {
    const page = more ? draftPage + 1 : 1
    const { data } = await factoryInboundApi.list({ mine: true, status: 'draft', page }, { signal: controller.signal, suppressToast: true })
    if (controller.signal.aborted) return
    draftPage = page
    drafts.value = more ? [...drafts.value, ...data.items] : data.items
    draftTotal.value = data.total
  } catch {
    if (!controller.signal.aborted) draftError.value = true
  } finally {
    if (!controller.signal.aborted) loadingDrafts.value = false
  }
}

function goNote(id) {
  return router.replace({ query: { note: String(id) } })
}

function goDrafts() {
  scanning.value = false
  if (noteId.value) return router.replace({ query: {} })
  loadDrafts()
}

async function discardCapture() {
  savedCapture.value = null
  await clearCapture(actor.value)
}

async function submitCapture(capture) {
  if (uploading.value) return
  const userId = actor.value
  const controller = new AbortController()
  uploadRequest = controller
  uploading.value = true
  uploadError.value = ''
  savedCapture.value = capture
  await storeCapture(userId, capture)
  try {
    await factoryInboundApi.settings({ signal: controller.signal, suppressToast: true })
    const result = await factoryInboundApi.upload(capture, controller.signal)
    await clearCapture(userId)
    if (!alive) return
    savedCapture.value = null
    if (!capture.original) msgWarning('原图超过上传限制，已保存校正图')
    scanning.value = false
    await goNote(result.data.id)
  } catch (error) {
    if (!controller.signal.aborted) {
      scanning.value = false
      uploadError.value = error.response?.data?.detail || '上传结果未确认，请查看草稿后再试。'
      await goDrafts()
    }
  } finally {
    uploading.value = false
  }
}

async function mutate(operation, { voided = false } = {}) {
  if (busy.value || !note.value?.editable) return false
  const id = note.value.id
  const version = note.value.version
  busy.value = true
  cancel()
  try {
    const { data } = await operation(id, version)
    if (!alive || noteId.value !== id) return false
    if (voided) await goDrafts()
    else if (pendingRecognition(data)) open(id, { clear: false })
    else note.value = data
    return true
  } catch (error) {
    if (alive && noteId.value === id && error.response?.status === 409) open(id, { clear: false })
    return false
  } finally {
    busy.value = false
  }
}

function changeLine(id, changes) {
  return mutate((noteId, version) => factoryInboundApi.editLine(noteId, id, { version, ...changes }))
}
function editLine(line) {
  editing.value = line
  editor.value = true
}
function editCandidate() {
  const line = candidate.value
  candidateId.value = null
  editLine(line)
}

function refreshBatch() {
  batchRefresh.value += 1
  open(noteId.value, { clear: false })
}
async function choose(select) {
  const id = candidateId.value
  const ok = await changeLine(id, { select })
  if (ok && !['choose', 'confirm', 'decide'].includes(note.value.lines.find(line => line.id === id)?.match_status)) candidateId.value = null
}
async function saveLine(values) {
  const ok = editing.value ? await changeLine(editing.value.id, { patch: values })
    : await mutate((id, version) => factoryInboundApi.addLine(id, { version, values }))
  if (ok) editor.value = false
}

async function confirmNumber() {
  let value
  try {
    const suggested = note.value.recognized_delivery_no || ''
    const result = await promptAction('请对照原单右上角的红色印刷编号。', '工厂单据编号', {
      inputValue: note.value.delivery_no || suggested, inputPattern: /^[0-9]{1,32}$/,
      inputErrorMessage: '请输入原单上的数字编号',
    })
    value = result.value
    await confirmAction('确认单据编号为 ' + value + '？', '核对单据编号')
  } catch { return }
  await mutate((id, version) => factoryInboundApi.confirmDelivery(id, { version, delivery_no: value, confirmed: true }))
}

async function retry(original) {
  if (note.value.lines.length) {
    try { await confirmAction('重新识别会替换本草稿的核对明细，是否继续？', '重新识别') }
    catch { return }
  }
  await mutate((id, version) => factoryInboundApi.recognize(id, { version, original }))
}

async function voidCurrent(duplicate) {
  try { await confirmDanger('作废', note.value.inbound_no) }
  catch { return }
  await mutate((id, version) => factoryInboundApi.void(id, {
    version, duplicate, reason: duplicate ? '核对为同一张工厂送货单' : '手动作废草稿',
  }), { voided: true })
}

watch(noteId, id => {
  scanning.value = false
  candidateId.value = null
  editor.value = false
  summary.value = false
  open(id)
  if (!id) loadDrafts()
}, { immediate: true })
onMounted(initialize)
onBeforeUnmount(() => {
  alive = false
  uploadRequest?.abort()
  draftRequest?.abort()
})
</script>

<style scoped>
.factory-scan {
  max-width: 680px;
  min-height: 100dvh;
  margin: auto;
  padding: 0 16px 16px;
  color: var(--el-text-color-primary);
}
.scan-head {
  position: sticky;
  top: 0;
  z-index: 2;
  display: grid;
  grid-template-columns: 1fr auto 1fr;
  align-items: center;
  padding: max(8px, env(safe-area-inset-top)) 0 8px;
  background: var(--el-bg-color-page);
}
.scan-head :deep(.glass-button) { justify-self: start; }
h1 { font-size: 18px; margin: 0; }
h2 { font-size: 16px; margin: 0; }
.work-card, .draft-card, .scan-foot {
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color);
  border-radius: 14px;
  padding: 14px;
}
.work-card { margin-bottom: 10px; }
.note-head, .draft-card, .scan-foot { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.note-head p { margin: 4px 0; }
.draft-card {
  width: 100%;
  cursor: pointer;
  color: inherit;
  font: inherit;
  text-align: left;
}
.draft-card small { display: block; margin-top: 4px; }
.new-note .capture-entry { min-height: 48px; }
.drafts, .review-group { display: grid; gap: 10px; }
.review-group { margin-bottom: 16px; }
.muted, small { color: var(--el-text-color-secondary); }
.review-actions, .resume { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.duplicate { border-color: var(--el-color-warning); }
.scan-foot {
  position: sticky;
  bottom: 0;
  z-index: 1;
  padding-bottom: max(14px, env(safe-area-inset-bottom));
}
@media (max-width: 450px) {
  .factory-scan { padding-inline: 10px; }
  .factory-scan :deep(.glass-button) { min-height: 44px; }
}
</style>
