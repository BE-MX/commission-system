<template>
  <div class="recording-panel">
    <div v-if="editable" class="recording-upload">
      <input ref="fileInput" type="file" class="hidden-input" :accept="ACCEPT" @change="onPick">
      <GlassButton variant="outline" left-icon="Microphone" :disabled="busy || rows.length >= MAX" @click="fileInput.click()">
        {{ picked ? '重新选择' : '选择录音' }}
      </GlassButton>
      <template v-if="picked">
        <span class="picked-name" :title="picked.name">{{ picked.name }} · {{ sizeLabel(picked.size) }}</span>
        <GlassButton variant="primary" :loading="busy" @click="upload">上传并解析</GlassButton>
      </template>
      <p class="hint">支持 m4a / mp3 / wav / aac / amr 等，单个不超过 200MB，每条跟进最多 {{ MAX }} 段。上传后即可保存或关闭，转写在后台完成。</p>
      <el-progress v-if="busy" :percentage="progress" :stroke-width="6" />
    </div>

    <div v-for="row in rows" :key="row.id" class="recording-card">
      <div class="recording-head">
        <span class="recording-name" :title="row.file_name">{{ row.file_name || `录音 ${row.id}` }}</span>
        <StatusBadge :value="row.asr_status" :dictionary="RECORDING_STATUS" size="small" />
        <span v-if="row.asr_status === 'queued' && row.queue_position" class="meta">排队第 {{ row.queue_position }}</span>
        <span v-if="row.duration_sec" class="meta">{{ durationLabel(row.duration_sec) }}</span>
        <span v-if="row.transcript_chars" class="meta">{{ row.transcript_chars }} 字</span>
        <button v-if="editable" type="button" class="remove" aria-label="移除录音" @click="$emit('remove', row)">×</button>
      </div>
      <p v-if="row.error_message && row.asr_status !== 'done'" class="error">{{ row.error_message }}</p>
      <div class="recording-actions">
        <GlassButton v-if="row.asr_status === 'done'" variant="link" left-icon="Download" @click="download(row)">下载 txt</GlassButton>
        <GlassButton v-if="row.asr_status === 'done'" variant="link" @click="toggleTranscript(row)">{{ openId === row.id ? '收起转写' : '查看转写' }}</GlassButton>
        <GlassButton v-if="row.asr_status === 'done' && allowOrganize" v-permission="'domestic_followup:write'" variant="link"
                     :loading="row.organize_status === 'running'" @click="organize(row)">
          {{ row.organize_status === 'done' ? '重新 AI 整理' : 'AI 整理' }}
        </GlassButton>
        <GlassButton v-if="row.asr_status === 'failed'" v-permission="'domestic_followup:write'" variant="link" @click="retry(row)">重新转写</GlassButton>
      </div>
      <div v-if="openId === row.id && details[row.id]" class="transcript">
        <p v-for="(s, i) in details[row.id].segments" :key="i"><time>{{ clock(s.start) }}</time><b>{{ s.speaker }}</b>{{ s.text }}</p>
        <pre v-if="!details[row.id].segments?.length">{{ details[row.id].transcript_text }}</pre>
      </div>
      <div v-if="row.organize_status === 'failed'" class="error">{{ row.organize_error }}</div>
      <section v-if="details[row.id]?.organize_result" class="organized">
        <h4>AI 整理建议 <small>（仅供参考，核对后再写进跟进）</small></h4>
        <p v-if="details[row.id].organize_result.summary"><b>摘要：</b>{{ details[row.id].organize_result.summary }}</p>
        <ul>
          <li v-for="(f, i) in details[row.id].organize_result.facts" :key="`f${i}`">
            {{ f.text }}<span class="quote" :class="{ unverified: !f.source.verified }">「{{ f.source.excerpt }}」{{ f.source.verified ? '' : '待核' }}</span>
          </li>
          <li v-for="(it, i) in details[row.id].organize_result.items" :key="`i${i}`">
            <StatusBadge :value="it.kind" :dictionary="ITEM_KIND_STATUS" size="small" /> {{ it.text }}
          </li>
          <li v-for="(s, i) in details[row.id].organize_result.next_steps" :key="`n${i}`">下一步：{{ s.text }}<span v-if="s.date_expression">（{{ s.date_expression }}）</span></li>
        </ul>
      </section>
    </div>
  </div>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import { apiError, followupApi } from '@/api/domesticFollowup'
import { downloadBlob } from '@/utils/download'
import { msgError, msgSuccessText } from '@/utils/feedback'
import { ITEM_KIND_STATUS, RECORDING_STATUS } from '../followupStatus'

const props = defineProps({
  recordings: { type: Array, default: () => [] },
  editable: { type: Boolean, default: false },
  followupId: { type: Number, default: null },
  allowOrganize: { type: Boolean, default: true },
  hotwords: { type: String, default: '' },
})
const emit = defineEmits(['uploaded', 'remove', 'update'])
const MAX = 3
const MAX_BYTES = 200 * 1024 * 1024
const ACCEPT = '.m4a,.mp3,.wav,.aac,.amr,.ogg,.opus,.flac,.webm,audio/*'
const EXTENSIONS = ACCEPT.split(',').filter(v => v.startsWith('.'))

const fileInput = ref(null)
const picked = ref(null)
const busy = ref(false)
const progress = ref(0)
const rows = ref([])
const details = reactive({})
const openId = ref(null)
let timer = null

watch(() => props.recordings, value => { rows.value = value.map(r => ({ ...r })); schedule() }, { immediate: true })

function sizeLabel(bytes) { return bytes >= 1048576 ? `${(bytes / 1048576).toFixed(1)}MB` : `${Math.ceil(bytes / 1024)}KB` }
function durationLabel(sec) { return `${Math.floor(sec / 60)}分${String(sec % 60).padStart(2, '0')}秒` }
function clock(sec) {
  const s = Math.floor(Number(sec) || 0)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

function onPick(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  const ext = `.${file.name.split('.').pop().toLowerCase()}`
  if (!EXTENSIONS.includes(ext)) return msgError('请选择录音文件（m4a / mp3 / wav / aac / amr 等）')
  if (file.size > MAX_BYTES) return msgError('录音不能超过 200MB')
  picked.value = file
}

async function upload() {
  if (!picked.value) return
  busy.value = true
  progress.value = 0
  try {
    const row = await followupApi.uploadRecording(picked.value, {
      followupId: props.followupId, hotwords: props.hotwords, onProgress: p => { progress.value = p },
    })
    picked.value = null
    if (!rows.value.some(r => r.id === row.id)) rows.value.push(row)
    emit('uploaded', row)
    emitUpdate()
    msgSuccessText('录音已上传，转写完成后可下载文本')
    schedule()
  } catch (e) {
    msgError(apiError(e, '录音上传失败'), e)
  } finally {
    busy.value = false
  }
}

function emitUpdate() { emit('update', rows.value.map(r => ({ ...r }))) }

const pending = () => rows.value.some(r => ['queued', 'running'].includes(r.asr_status) || r.organize_status === 'running')

function schedule() {
  clearTimeout(timer)
  if (pending()) timer = setTimeout(refresh, 20000)
}

async function refresh() {
  const targets = rows.value.filter(r => ['queued', 'running'].includes(r.asr_status) || r.organize_status === 'running')
  await Promise.all(targets.map(async row => {
    try {
      const fresh = await followupApi.recording(row.id)
      Object.assign(row, fresh)
      if (fresh.organize_result || fresh.segments) details[row.id] = fresh
    } catch { /* 下一轮再试，不打断录入 */ }
  }))
  emitUpdate()
  schedule()
}

async function load(row) {
  const fresh = await followupApi.recording(row.id)
  Object.assign(row, fresh)
  details[row.id] = fresh
}

async function toggleTranscript(row) {
  if (openId.value === row.id) { openId.value = null; return }
  try {
    if (!details[row.id]) await load(row)
    openId.value = row.id
  } catch (e) { msgError(apiError(e, '转写加载失败'), e) }
}

async function download(row) {
  try { downloadBlob(await followupApi.downloadTranscript(row.id), `录音转写_${row.id}.txt`) }
  catch (e) { msgError(apiError(e, '下载失败'), e) }
}

async function organize(row) {
  try {
    Object.assign(row, await followupApi.organizeRecording(row.id))
    schedule()
  } catch (e) { msgError(apiError(e, 'AI 整理失败'), e) }
}

async function retry(row) {
  try {
    Object.assign(row, await followupApi.retryRecording(row.id))
    schedule()
  } catch (e) { msgError(apiError(e, '重试失败'), e) }
}

watch(rows, () => rows.value.forEach(r => { if (r.organize_status === 'done' && !details[r.id]) load(r).catch(() => {}) }),
  { immediate: true })
onBeforeUnmount(() => clearTimeout(timer))
</script>

<style scoped>
.recording-panel { display: flex; flex-direction: column; gap: 10px; }
.recording-upload { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.hidden-input { display: none; }
.picked-name { max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-secondary); }
.hint { width: 100%; margin: 0; color: var(--text-secondary); font-size: 12px; }
.recording-card { border: 1px solid var(--border-color); border-radius: var(--radius-md, 8px); padding: 10px 12px; }
.recording-head { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }
.recording-name { font-weight: 600; max-width: 280px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.meta { color: var(--text-secondary); font-size: 12px; }
.remove { margin-left: auto; border: 0; background: none; cursor: pointer; color: var(--text-secondary); font-size: 16px; }
.recording-actions { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 4px; }
.error { margin: 6px 0 0; color: var(--color-danger-text); font-size: 12px; }
.transcript { max-height: 320px; overflow: auto; margin-top: 8px; padding: 8px; border-radius: var(--radius-sm, 6px); background: var(--color-success-bg); }
.transcript p { margin: 0 0 4px; line-height: 1.6; }
.transcript time { color: var(--text-secondary); font-size: 12px; margin-right: 6px; }
.transcript b { margin-right: 4px; }
.transcript pre { white-space: pre-wrap; margin: 0; }
.organized { margin-top: 8px; padding-top: 8px; border-top: 1px dashed var(--border-color); }
.organized h4 { margin: 0 0 6px; font-size: 13px; }
.organized small { color: var(--text-secondary); font-weight: normal; }
.organized ul { margin: 4px 0; padding-left: 18px; }
.quote { margin-left: 4px; color: var(--text-secondary); font-size: 12px; }
.quote.unverified { color: var(--color-warning-text); }
</style>
