<template>
  <div>
    <el-dialog :model-value="!!desk.dialog.value" :title="titles[desk.dialog.value]" width="480px" append-to-body :close-on-click-modal="!desk.saving.value" :close-on-press-escape="!desk.saving.value" destroy-on-close @update:model-value="v => { if (!v && !desk.saving.value) desk.dialog.value = '' }">
      <el-form label-position="top" @submit.prevent="desk.save">
        <template v-if="kind === 'note'"><el-form-item label="关键备注 · 仅本人"><el-input v-model="form.remark" type="textarea" :rows="5" maxlength="600" show-word-limit /></el-form-item></template>
        <template v-if="kind === 'date'"><el-form-item label="下次跟进日期（可清空）"><el-date-picker v-model="form.next_followup_date" value-format="YYYY-MM-DD" /></el-form-item><el-form-item label="跟进说明"><el-input v-model="form.next_followup_remark" type="textarea" /></el-form-item></template>
        <template v-if="kind === 'grade'"><el-alert title="分级为公司共享信息，其他归属业务员也会看到。" :closable="false" /><el-form-item label="客户等级"><el-select v-model="form.grade"><el-option v-for="grade in detail?.grade_options || []" :key="grade.value || grade" :label="grade.label || grade" :value="grade.value || grade" /></el-select></el-form-item><p v-if="!detail?.grade_options?.length">等级字典不可用，请联系管理员。</p></template>
        <template v-if="kind === 'snooze'"><el-form-item label="稍后提醒日期"><el-date-picker v-model="form.date" value-format="YYYY-MM-DD" :disabled-date="d => formatBeijingDate(d) <= currentBeijingDate()" /></el-form-item></template>
        <template v-if="kind === 'record'"><el-form-item label="渠道"><el-select v-model="form.channel" @change="sampleDate"><el-option v-for="(label, key) in CHANNELS" :key="key" :label="label" :value="key" /></el-select></el-form-item><el-form-item label="跟进内容" required><el-input v-model="form.content" type="textarea" :rows="4" maxlength="4000" /></el-form-item><el-form-item label="发生时间 · 北京时间" required><el-input v-model="form.happened_at" type="datetime-local" step="1" @change="sampleDate" /></el-form-item><el-form-item label="下次跟进（选填，可清空）"><el-date-picker v-model="form.next_followup_date" value-format="YYYY-MM-DD" /></el-form-item><p v-if="form.channel === 'sample'" class="muted">寄样默认 10 个工作日后跟进，可修改或清空。</p></template>
        <template v-if="kind === 'link'"><el-form-item label="搜索本人私海客户"><el-input v-model="desk.linkKeyword.value" clearable @input="desk.searchLinks" /></el-form-item><el-form-item label="手动确认客户" required><el-select v-model="form.company_id" filterable><el-option v-for="customer in desk.linkOptions.value" :key="customer.company_id" :label="customer.name" :value="String(customer.company_id)" /></el-select></el-form-item></template>
        <el-alert v-if="desk.saveError.value" :title="desk.saveError.value" type="error" :closable="false" />
        <div v-if="desk.conflict.value" class="conflict"><p>记录已被更新。本地输入已保留，请核对最新版本后重试。</p><el-button @click="reloadConflict">载入最新版本号，保留我的内容</el-button></div>
        <div class="dialog-actions"><el-button :disabled="desk.saving.value" @click="desk.dialog.value = ''">取消</el-button><el-button type="primary" native-type="submit" :loading="desk.saving.value" :disabled="kind === 'grade' && !detail?.grade_options?.length">保存</el-button></div>
      </el-form>
    </el-dialog>
    <el-dialog v-model="waVisible" title="确认 WhatsApp 联系目标" width="480px" append-to-body>
      <p>草稿由你核对并亲自发送；打开聊天不会标记已跟进。</p>
      <div v-for="target in detail?.wa_targets || []" :key="target.conversation_uid" class="wa-target"><span>{{ target.name || target.phone }}</span><el-button @click="openWhatsApp(target)">打开 ↗</el-button></div>
      <el-alert v-if="waError" :title="waError" type="error" :closable="false" />
    </el-dialog>
    <el-dialog v-model="copyOpen" title="复制草稿" width="480px" append-to-body><el-input :model-value="copyText" type="textarea" :rows="7" readonly aria-label="请选中并复制草稿" /></el-dialog>
  </div>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { currentBeijingDate, formatBeijingDate } from '@/utils/datetime'
import { clientDeskApi } from '@/api/clientDesk'
import { msgSuccessText } from '@/utils/feedback'
import { CHANNELS, copyOrFallback, revalidatedDraft, safeDestination } from './deskController'

const props = defineProps({ desk: { type: Object, required: true } })
const titles = { note: '关键备注', date: '下次跟进', grade: '客户分级', record: '记一笔', snooze: '稍后提醒', link: '关联到我的客户' }
const kind = computed(() => props.desk.dialog.value)
const form = computed(() => props.desk.form.value)
const detail = computed(() => props.desk.detail.value)
const waVisible = ref(false), waError = ref(''), copyOpen = ref(false), copyText = ref('')
watch([() => props.desk.selected.value, () => props.desk.suggestion.value?.id], () => { copyOpen.value = false; copyText.value = '' })

let sampleGeneration = 0
async function sampleDate() {
  const generation = ++sampleGeneration, current = form.value
  if (current.channel !== 'sample' || !current.happened_at) return
  const happened = current.happened_at
  try {
    const result = await clientDeskApi.sampleDate(happened.slice(0, 10))
    if (generation === sampleGeneration && kind.value === 'record' && form.value.channel === 'sample' && form.value.happened_at === happened) form.value.next_followup_date = result.date
  } catch { props.desk.saveError.value = '寄样跟进日期暂时无法计算，请手动选择日期。' }
}
async function reloadConflict() {
  try {
    const current = await clientDeskApi.customer(props.desk.selected.value)
    if (kind.value === 'grade') form.value.expected_grade = current.grade
    else form.value.expected_version = current.personal_state.manual_version
    props.desk.conflict.value = null; props.desk.saveError.value = ''
  } catch { props.desk.saveError.value = '最新版本读取失败，你的内容已保留，请稍后重试。' }
}
function openWa() { waError.value = ''; waVisible.value = true }
async function openWhatsApp(target) {
  waError.value = ''
  // Reserve the user-initiated tab before awaiting live authorization to avoid popup blocking.
  const popup = window.open('about:blank', '_blank')
  if (popup) popup.opener = null
  try {
    const result = await clientDeskApi.waOpen(props.desk.selected.value, { account_uid: target.account_uid, conversation_uid: target.conversation_uid, suggestion_id: props.desk.suggestion.value?.id })
    const destination = safeDestination(result.url)
    if (!destination) throw new Error('联系目标已失效')
    if (popup) { popup.document.referrerPolicy = 'no-referrer'; popup.location.replace(destination) } else window.location.assign(destination)
  } catch { popup?.close(); waError.value = '联系目标或来源已变更，请刷新客户档案后重试。' }
}
async function copyDraft() {
  const desk = props.desk, customer = desk.selected.value, suggestionId = desk.suggestion.value?.id
  const isCurrent = () => desk.selected.value === customer && String(desk.suggestion.value?.id) === String(suggestionId)
  copyOpen.value = false; copyText.value = ''
  try {
    // Copy is a new disclosure boundary: re-read live dependencies rather than the cached draft.
    const fresh = await revalidatedDraft(clientDeskApi.freshCustomer, customer, suggestionId, isCurrent)
    desk.detail.value = fresh
    const result = await copyOrFallback(fresh.suggestion.draft, text => navigator.clipboard.writeText(text), () => isCurrent() && desk.suggestion.value?.draft === fresh.suggestion.draft)
    if (result?.copied) msgSuccessText('草稿已复制')
    else if (result) { copyText.value = result.text; copyOpen.value = true }
  } catch {
    if (isCurrent()) { desk.detail.value = null; desk.detailError.value = '草稿、资料或授权已变化，请重新查看客户资料。' }
  }
}
defineExpose({ copyDraft, openWa })
</script>

<style src="./board.css" scoped></style>
<style scoped>
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 22px; }
.wa-target { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin: 12px 0; }
.conflict { margin-top: 10px; padding: 10px; background: var(--button-warning-soft); font-size: 12px; }
</style>
