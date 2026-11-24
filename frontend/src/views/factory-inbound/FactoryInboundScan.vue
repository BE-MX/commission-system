<template>
  <main class="inbound-station">
    <header class="station-header">
      <div class="station-brand"><img src="/shipping-app/icon-180.png" alt="" width="32" height="32" /><span>莱莎到货入库</span></div>
      <button v-if="noteId || scanning" class="station-link" type="button" :disabled="uploading" @click="goDrafts"><ArrowLeft />返回草稿</button>
      <button v-else class="station-link" type="button" @click="router.push('/dashboard')"><HomeFilled />工作台</button>
    </header>

    <section v-if="initError" class="station-error" role="alert">
      <Warning />
      <div class="notice-body"><strong>{{ initError }}</strong><div class="notice-actions"><button class="station-secondary" type="button" @click="initialize">重试</button></div></div>
    </section>
    <div v-else-if="!settings" class="station-card skeleton-card"><el-skeleton :rows="2" animated /></div>

    <template v-else-if="scanning">
      <DocumentScanner v-if="!uploading" finish="emit" finish-label="识别这张" default-effect="enhanced"
        :max-upload-bytes="settings.max_upload_bytes" @captured="submitCapture" @cancel="goDrafts" />
      <section v-else class="station-card uploading-card" role="status">
        <div class="sweep compact" aria-hidden="true"><span /></div>
        <h2>正在上传照片</h2>
        <p>请保持网络连接，上传完成后自动开始识别</p>
      </section>
    </template>

    <section v-else-if="!noteId">
      <button class="scan-button" type="button" :disabled="uploading" @click="scanning = true"><Camera /><span>拍工厂送货单</span><ArrowRight /></button>
      <p class="scan-hint">整张送货单放平拍摄，识别约 20–60 秒，期间可以先离开</p>

      <section v-if="savedCapture" class="station-warning" role="status">
        <Picture />
        <div class="notice-body">
          <strong>上次的照片还没上传</strong>
          <p>照片暂存在这台手机上，可以继续上传或清除。</p>
          <div class="notice-actions">
            <button class="station-secondary" type="button" :disabled="uploading" @click="submitCapture(savedCapture)">继续上传</button>
            <button class="station-secondary danger" type="button" :disabled="uploading" @click="discardCapture">清除照片</button>
          </div>
        </div>
      </section>
      <section v-if="uploadError" class="station-error" role="alert"><Warning /><div class="notice-body">{{ uploadError }}</div></section>

      <div class="section-title"><h2>我的草稿</h2><span v-if="draftTotal">共 {{ draftTotal }} 张</span></div>
      <section v-if="draftError" class="station-error" role="alert">
        <Warning />
        <div class="notice-body"><strong>无法读取草稿</strong><div class="notice-actions"><button class="station-secondary" type="button" @click="loadDrafts()">重试</button></div></div>
      </section>
      <div v-else-if="loadingDrafts && !drafts.length" class="station-card skeleton-card"><el-skeleton :rows="3" animated /></div>
      <div v-else-if="!drafts.length" class="empty-card"><strong>暂无草稿</strong>拍下送货单后，识别结果会保存在这里</div>
      <ul v-else class="draft-list">
        <InboundDraftRow v-for="draft in drafts" :key="draft.id" :draft="draft"
          :open="openDraftId === draft.id" :disabled="uploading" :busy="removingDraft"
          @reveal="openDraftId = $event ? draft.id : null"
          @open="goNote(draft.id)" @remove="removeDraft(draft)" />
      </ul>
      <button v-if="drafts.length < draftTotal" class="station-secondary more-button" type="button" :disabled="loadingDrafts || removingDraft" @click="loadDrafts(true)">
        {{ loadingDrafts ? '正在加载…' : '加载更多草稿' }}
      </button>
    </section>

    <section v-else-if="readError" class="station-error" role="alert">
      <Warning />
      <div class="notice-body"><strong>{{ readError }}</strong><div class="notice-actions"><button class="station-secondary" type="button" @click="open(noteId)">重新读取</button></div></div>
    </section>
    <div v-else-if="!note" class="station-card skeleton-card"><el-skeleton :rows="4" animated /></div>

    <template v-else>
      <section class="station-card record-card">
        <div class="record-top">
          <div class="record-main">
            <span class="eyebrow">工厂单据编号</span>
            <h1 class="record-no" :class="{ pending: !draftNumber(note) }">{{ draftNumber(note) || '编号待确认' }}</h1>
            <span v-if="note.delivery_no" class="pill tone-success">已确认</span>
            <span v-else-if="note.recognized_delivery_no" class="pill tone-warning">识别结果，待确认</span>
          </div>
          <InboundPhoto class="record-photo" :note="note" />
        </div>
        <dl class="record-meta">
          <div><dt>入库草稿</dt><dd>{{ note.inbound_no }}</dd></div>
          <div><dt>送货日期</dt><dd>{{ deliveryDate(note) }}</dd></div>
          <div><dt>状态</dt><dd>{{ noteStatus(note) }}</dd></div>
        </dl>
        <button v-if="canConfirmNumber" :class="note.delivery_no || note.duplicate ? 'station-secondary' : 'submit-button'" type="button" :disabled="busy" @click="confirmNumber">
          {{ note.delivery_no || note.duplicate ? '更正单据编号' : '对照原单，确认单据编号' }}
        </button>
      </section>

      <section v-if="pendingRecognition(note)" class="station-card recognizing" role="status">
        <div class="sweep" aria-hidden="true"><span /></div>
        <h2>正在识别送货单</h2>
        <p>{{ delayed ? '识别仍在进行，可以稍后从「我的草稿」继续。' : '约需 20–60 秒，可以先离开，结果会保存在草稿里。' }}</p>
        <button v-if="delayed" class="station-secondary" type="button" @click="open(noteId, { clear: false })"><Refresh />刷新识别状态</button>
      </section>

      <section v-if="reviewing && note.duplicate" class="station-warning">
        <Warning />
        <div class="notice-body">
          <strong>疑似重拍：可能是同一张单</strong>
          <p>已有草稿 {{ note.duplicate.inbound_no }} · {{ note.duplicate.creator || '操作人未登记' }}</p>
          <div class="notice-actions">
            <InboundPhoto v-if="note.duplicate.id" :note="note.duplicate" />
            <button v-if="note.duplicate.id" class="station-secondary" type="button" @click="goNote(note.duplicate.id)">打开原草稿</button>
            <p v-else>请联系创建人或管理员核对原单</p>
            <button v-if="note.editable" class="station-secondary danger" type="button" :disabled="busy" @click="voidCurrent(true)">是同一张，作废本草稿</button>
          </div>
        </div>
      </section>

      <section v-if="reviewing && note.recognition_error" class="station-error" role="alert">
        <Warning />
        <div class="notice-body">
          <strong>{{ note.recognition_error }}</strong>
          <div v-if="note.editable && note.recognition_status === 'failed'" class="notice-actions">
            <button class="submit-button" type="button" :disabled="busy" @click="scanning = true"><Camera />重拍送货单</button>
          </div>
        </div>
      </section>

      <section v-if="reviewing && note.lines.length" class="station-card">
        <div class="section-heading"><h2>核对进度</h2><span>{{ handledCount }} / {{ note.lines.length }} 行已核对</span></div>
        <div class="progress-track" role="progressbar" aria-label="已核对行数" :aria-valuetext="handledCount + ' / ' + note.lines.length + ' 行已核对'" :aria-valuenow="handledCount" aria-valuemin="0" :aria-valuemax="note.lines.length">
          <span :style="{ transform: 'scaleX(' + handledCount / note.lines.length + ')' }" />
        </div>
        <ul class="tally">
          <li v-for="item in tallies" :key="item.label"><span class="pill" :class="'tone-' + item.tone"><b>{{ item.count }}</b>{{ item.label }}</span></li>
        </ul>
      </section>

      <InboundBatchStatus :note-id="note.id" :refresh="batchRefresh" @batch-checked="open(note.id, { clear: false })" />

      <template v-if="reviewing">
        <section v-for="group in groups" :key="group.ref" class="review-group">
          <div class="group-heading"><h2>{{ /^\d/.test(group.ref) ? '单号 ' + group.ref : group.ref }}</h2><span>{{ group.items.length }} 行</span></div>
          <InboundReviewLine v-for="line in group.items" :key="line.id" :line="line" :editable="note.editable" :busy="busy"
            @change="changeLine(line.id, $event)" @edit="editLine(line)" @choose="candidateId = line.id" />
        </section>

        <section v-if="note.editable" class="station-card">
          <div class="section-heading"><h2>其他操作</h2></div>
          <div class="tool-grid">
            <button class="tool" type="button" :disabled="busy" @click="editLine(null)"><Plus />手工录入一行</button>
            <button v-if="!hasSubmittedLines" class="tool" type="button" :disabled="busy" @click="retry(false)"><Refresh />重新识别</button>
            <button v-if="!hasSubmittedLines && note.has_original" class="tool" type="button" :disabled="busy" @click="retry(true)"><Picture />用原图识别</button>
            <button v-if="!hasSubmittedLines" class="tool danger" type="button" :disabled="busy" @click="voidCurrent(false)"><Delete />作废草稿</button>
          </div>
        </section>

        <footer v-if="note.lines.length" class="scan-foot">
          <div class="foot-summary"><span>已勾选</span><strong>{{ selected.length }} 行 · {{ selectedQuantity }} 件</strong></div>
          <button class="submit-button" type="button" :disabled="!selected.length" @click="summary = true">核对汇总<ArrowRight /></button>
        </footer>
        <CandidateSheet :line="candidate" :busy="busy" @close="candidateId = null" @edit="editCandidate"
          @select="choose" />
        <LineEditDialog :open="editor" :line="editing" :types="settings.line_types" :busy="busy"
          @close="editor = false" @save="saveLine" />
        <InboundSummarySheet :note="note" :open="summary" :sync-enabled="settings.sync_enabled"
          @close="summary = false" @batch-checked="refreshBatch" />
      </template>
    </template>
    <div class="station-footnote">莱莎方舟 · 工厂到货入库</div>
  </main>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, ArrowRight, Camera, Delete, HomeFilled, Picture, Plus, Refresh, Warning } from '@element-plus/icons-vue'
import DocumentScanner from '@/components/document-scanner/DocumentScanner.vue'
import { factoryInboundApi } from '@/api/factoryInbound'
import { useAuthStore } from '@/stores/auth'
import { confirmAction, confirmDanger, msgSuccessText, msgWarning, promptAction } from '@/utils/feedback'
import CandidateSheet from './components/CandidateSheet.vue'
import InboundBatchStatus from './components/InboundBatchStatus.vue'
import InboundDraftRow from './components/InboundDraftRow.vue'
import InboundPhoto from './components/InboundPhoto.vue'
import InboundReviewLine from './components/InboundReviewLine.vue'
import InboundSummarySheet from './components/InboundSummarySheet.vue'
import LineEditDialog from './components/LineEditDialog.vue'
import { clearCapture, loadCapture, storeCapture } from './composables/pendingCapture'
import { useInboundRecognition } from './composables/useInboundRecognition'
import { deliveryDate, groupLines, lineTally, noteStatus, noteTone, pendingRecognition } from './inboundLabels'

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
const openDraftId = ref(null)
const removingDraft = ref(false)
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
const reviewing = computed(() => note.value?.status === 'draft' && !pendingRecognition(note.value))
const canConfirmNumber = computed(() => reviewing.value && note.value.editable && !hasSubmittedLines.value
  && note.value.recognition_status === 'done')
const tallies = computed(() => lineTally(note.value?.lines || []))
const handledCount = computed(() => tallies.value.filter(item => item.handled).reduce((sum, item) => sum + item.count, 0))
const draftNumber = item => item.delivery_no || item.recognized_delivery_no || ''
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
  if (!more) {
    openDraftId.value = null
    drafts.value = []
  }
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

async function removeDraft(draft) {
  if (uploading.value || removingDraft.value) return
  removingDraft.value = true
  try {
    await confirmDanger('删除', draft.inbound_no, '删除后，单据将移出「我的草稿」，并保留为已作废记录。')
    if (!alive) return
    await factoryInboundApi.void(draft.id, { version: draft.version, duplicate: false, reason: '手动作废草稿' })
    if (!alive) return
    msgSuccessText('草稿已删除')
    if (!noteId.value && !scanning.value) await loadDrafts()
  } catch (error) {
    // OCR or another device may have changed this draft since the list was loaded.
    if (alive && !noteId.value && !scanning.value && [404, 409].includes(error.response?.status)) await loadDrafts()
  } finally {
    removingDraft.value = false
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
<style src="./pills.css" scoped></style>
<style src="./scan.css" scoped></style>
