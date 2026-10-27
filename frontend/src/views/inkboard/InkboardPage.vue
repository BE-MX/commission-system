<template>
  <main class="inkboard-page">
    <header class="page-heading">
      <div><h1>Kindle 看板</h1><p>待办来自个人任务中心。设备约每 5 分钟同步一次。</p></div>
      <GlassButton :loading="loading" @click="load">刷新</GlassButton>
    </header>
    <el-alert v-if="error" :title="error" type="error" show-icon :closable="false" />
    <section class="board-grid">
      <section class="board-card">
        <div class="section-heading"><h2>我的设备</h2><GlassButton v-permission="'inkboard:write'" @click="bind">绑定设备</GlassButton></div>
        <el-empty v-if="!devices.length" description="尚未绑定 Kindle" :image-size="70" />
        <article v-for="item in devices" :key="item.id" class="entry">
          <div><strong>{{ item.name }}</strong><p>{{ item.revoked_at ? '已撤销' : `最近接收：${date(item.last_received_at)}` }}</p></div>
          <GlassButton v-if="!item.revoked_at" v-permission="'inkboard:write'" variant="link" link-tone="danger" @click="revoke(item)">撤销</GlassButton>
        </article>
      </section>
      <section class="board-card">
        <div class="section-heading"><h2>置顶备忘 <small>{{ notes.length }}/10</small></h2><GlassButton v-permission="'inkboard:write'" :disabled="notes.length >= 10" @click="editNote()">新建备忘</GlassButton></div>
        <el-empty v-if="!notes.length" description="添加要常驻在 Kindle 上的备忘" :image-size="70" />
        <article v-for="item in notes" :key="item.id" class="entry note-entry">
          <div><strong>{{ item.title }}</strong><p class="note-body">{{ item.body }}</p></div>
          <div class="entry-actions"><GlassButton v-permission="'inkboard:write'" variant="link" @click="editNote(item)">编辑</GlassButton><GlassButton v-permission="'inkboard:write'" variant="link" link-tone="danger" @click="removeNote(item)">删除</GlassButton></div>
        </article>
      </section>
    </section>
    <section class="board-card">
      <div class="section-heading"><h2>发送消息</h2><span class="muted">仅发送到本人绑定的设备</span></div>
      <el-form label-position="top" @submit.prevent="send">
        <el-form-item label="标题"><el-input v-model="draft.title" maxlength="120" show-word-limit /></el-form-item>
        <el-form-item label="内容"><el-input v-model="draft.body" type="textarea" :rows="3" maxlength="1000" show-word-limit /></el-form-item>
        <div class="compose-actions"><el-checkbox v-model="draft.high">重要消息</el-checkbox><GlassButton v-permission="'inkboard:write'" variant="primary" :loading="sending" :disabled="!draft.title.trim() || !draft.body.trim()" @click="send">{{ retryKey ? '重试同一条消息' : '发送到 Kindle' }}</GlassButton></div>
      </el-form>
      <p v-if="sendError" role="alert" class="send-error">{{ sendError }}。可重试同一条消息，系统会核对请求编号。</p>
      <el-empty v-if="!messages.length" description="尚未发送消息" :image-size="70" />
      <article v-for="item in messages" :key="item.id" class="entry message-entry">
        <div><strong>{{ item.priority === 'high' ? '重要 · ' : '' }}{{ item.title }}</strong><p class="note-body">{{ item.body }}</p><p>{{ date(item.created_at) }} · {{ item.withdrawn ? '已撤回' : `已接收 ${item.received_count}/${item.device_count} · 已读 ${item.read_count}/${item.device_count}` }}</p></div>
        <GlassButton v-if="!item.withdrawn" v-permission="'inkboard:write'" variant="link" link-tone="danger" @click="withdraw(item)">撤回</GlassButton>
      </article>
      <p class="muted">显示最近 50 条。消息保留 7 天；撤回后设备在下次同步时移除。</p>
    </section>
    <el-dialog v-model="noteOpen" :title="noteDraft.id ? '编辑备忘' : '新建备忘'" width="480" class="inkboard-dialog" :close-on-click-modal="false">
      <el-form label-position="top"><el-form-item label="标题"><el-input v-model="noteDraft.title" maxlength="120" /></el-form-item><el-form-item label="内容"><el-input v-model="noteDraft.body" type="textarea" :rows="6" maxlength="2000" show-word-limit /></el-form-item></el-form>
      <template #footer><GlassButton @click="noteOpen = false">取消</GlassButton><GlassButton variant="primary" :loading="saving" :disabled="!noteDraft.title.trim() || !noteDraft.body.trim()" @click="save">保存</GlassButton></template>
    </el-dialog>
    <el-dialog v-model="tokenOpen" title="设备凭证仅显示这一次" width="480" class="inkboard-dialog" :close-on-click-modal="false" @closed="issued = null">
      <p>下载配置后，通过 USB 放入安装包的指定目录。文件含设备凭证，请勿转发。</p>
      <p>绑定 {{ issued?.name }} 后，在 Kindle 的方舟看板里载入此配置。</p>
      <template #footer><GlassButton @click="tokenOpen = false">关闭</GlassButton><GlassButton variant="primary" @click="downloadConfig">下载设备配置</GlassButton></template>
    </el-dialog>
  </main>
</template>

<script setup>
import { onBeforeUnmount, reactive, ref, watch } from 'vue'
import { useAuthStore } from '@/stores/auth'
import GlassButton from '@/components/GlassButton.vue'
import * as api from '@/api/inkboard'
import { confirmAction, isFeedbackCancelled, msgError, msgSuccess, promptAction } from '@/utils/feedback'
import { formatBeijingDateTime } from '@/utils/datetime'

const auth = useAuthStore()
const devices = ref([]), notes = ref([]), messages = ref([])
const loading = ref(false), saving = ref(false), sending = ref(false), error = ref(''), sendError = ref('')
const noteOpen = ref(false), tokenOpen = ref(false), issued = ref(null)
const draft = reactive({ title: '', body: '', high: false })
const noteDraft = reactive({ id: null, title: '', body: '', version: 1 })
const retryKey = ref('')
let sentPayload = null, generation = 0, controller
const date = value => value ? formatBeijingDateTime(value) : '尚未接收'
const key = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), b => b.toString(16).padStart(2, '0')).join('')

async function load() {
  const current = ++generation
  controller?.abort(); controller = new AbortController()
  loading.value = true; error.value = ''
  try {
    const options = { signal: controller.signal, suppressToast: true }
    const result = await Promise.all([api.listDevices(options), api.listNotes(options), api.listMessages(options)])
    if (current !== generation) return
    ;[devices.value, notes.value, messages.value] = result.map(r => r.data)
  } catch (e) {
    if (current === generation && e.code !== 'ERR_CANCELED') error.value = '读取失败，请重试'
  } finally { if (current === generation) loading.value = false }
}
async function bind() {
  const current = generation
  try {
    const { value } = await promptAction('设备名称', '绑定 Kindle', { inputValue: 'Kindle PW3', inputPattern: /\S/, inputErrorMessage: '请输入设备名称', confirmButtonText: '绑定', cancelButtonText: '取消' })
    if (current !== generation) return
    const result = await api.bindDevice({ name: value.trim() })
    if (current !== generation) return
    issued.value = result.data; tokenOpen.value = true
    await load()
  } catch (e) { if (!isFeedbackCancelled(e)) msgError('绑定失败', e) }
}
function downloadConfig() {
  if (!issued.value) return
  const config = { url: `${location.origin}/api/inkboard`, token: issued.value.token }
  const url = URL.createObjectURL(new Blob([JSON.stringify(config, null, 2)], { type: 'application/json' }))
  const anchor = document.createElement('a'); anchor.href = url; anchor.download = 'ark-board.local.json'; anchor.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
async function revoke(item) {
  try { await confirmAction(`撤销「${item.name}」的访问？`, '撤销设备'); await api.revokeDevice(item.id); await load() }
  catch (e) { if (!isFeedbackCancelled(e)) msgError('撤销失败', e) }
}
function editNote(item) { Object.assign(noteDraft, item || { id: null, title: '', body: '', version: 1 }); noteOpen.value = true }
async function save() {
  if (saving.value) return
  const current = generation
  saving.value = true
  try { await api.saveNote({ ...noteDraft }); if (current !== generation) return; noteOpen.value = false; await load() }
  catch (e) { msgError('保存失败，请刷新后核对版本', e) }
  finally { saving.value = false }
}
async function removeNote(item) {
  try { await confirmAction(`删除备忘「${item.title}」？`, '删除备忘'); await api.deleteNote(item); await load() }
  catch (e) { if (!isFeedbackCancelled(e)) msgError('删除失败', e) }
}
async function send() {
  if (sending.value) return
  const payload = { title: draft.title.trim(), body: draft.body.trim(), priority: draft.high ? 'high' : 'normal' }
  if (!payload.title || !payload.body) return
  if (retryKey.value && JSON.stringify(payload) !== sentPayload) {
    msgError('上一条消息结果未确认，请恢复原内容并重试，再发送新消息'); return
  }
  retryKey.value ||= key(); sentPayload = JSON.stringify(payload)
  const current = generation
  sending.value = true; sendError.value = ''
  try {
    await api.sendMessage({ ...payload, request_key: retryKey.value })
    if (current !== generation) return
    retryKey.value = ''; sentPayload = null; draft.title = ''; draft.body = ''; draft.high = false
    msgSuccess('消息排队'); await load()
  } catch (e) { if (current === generation) sendError.value = '消息提交结果未确认' }
  finally { sending.value = false }
}
async function withdraw(item) {
  try { await confirmAction(`撤回消息「${item.title}」？`, '撤回消息'); await api.withdrawMessage(item.id); await load() }
  catch (e) { if (!isFeedbackCancelled(e)) msgError('撤回失败', e) }
}
watch(() => auth.user?.id, () => {
  ++generation; controller?.abort(); devices.value = []; notes.value = []; messages.value = []
  issued.value = null; tokenOpen.value = false; noteOpen.value = false; retryKey.value = ''; sentPayload = null
  draft.title = ''; draft.body = ''; draft.high = false
  if (auth.user) load()
}, { immediate: true })
onBeforeUnmount(() => { ++generation; controller?.abort(); issued.value = null })
</script>

<style scoped>
.inkboard-page { display: grid; gap: 20px; max-width: 1200px; margin: 0 auto; padding: 24px; color: var(--text-primary); }
.page-heading, .section-heading, .entry, .compose-actions { display: flex; justify-content: space-between; align-items: center; gap: 16px; }
h1 { font-size: 24px; margin: 0; } h2 { font-size: 17px; margin: 0; } small { font-weight: 400; }
p { color: var(--text-secondary); line-height: 1.6; font-size: 13px; margin: 8px 0; }
.board-grid { display: grid; grid-template-columns: 1fr 1.5fr; gap: 20px; align-items: start; }
.board-card { background: var(--button-surface); border: 1px solid var(--border-color); border-radius: 16px; padding: 24px; min-width: 0; }
.section-heading { margin-bottom: 20px; flex-wrap: wrap; }.entry { border-top: 1px solid var(--border-color); padding: 16px 0; }
.entry > div { min-width: 0; }.note-entry, .message-entry { align-items: start; }.note-body { white-space: pre-wrap; overflow-wrap: anywhere; }
.entry-actions { display: flex; gap: 8px; flex-shrink: 0; }.muted { color: var(--text-secondary); font-size: 13px; }.send-error { color: var(--button-danger-text); }
:global(.inkboard-dialog) { max-width: calc(100vw - 28px); }
@media (max-width: 760px) { .board-grid { grid-template-columns: 1fr; }.inkboard-page { padding: 14px; }.board-card { padding: 18px; }.page-heading { align-items: start; } }
</style>
