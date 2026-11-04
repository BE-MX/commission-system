<template>
  <el-dialog :model-value="e.visible.value" title="修改已提交跟进" width="760px" class="followup-edit-dialog" append-to-body
             :close-on-click-modal="false" :show-close="!e.saving.value" :before-close="close">
    <div v-loading="e.loading.value">
      <el-alert v-if="e.error.value" :title="e.error.value" type="error" :closable="false" show-icon>
        <GlassButton v-if="e.conflict.value || e.uncertain.value || !e.form.value" variant="link" @click="reload">重新载入最新记录</GlassButton>
      </el-alert>
      <template v-if="e.form.value">
        <p>{{ e.record.value.shop_name }} · 原录入人：{{ e.record.value.author_name }}</p>
        <el-alert title="未完成待办随修改同步；已完成回访和异常处理结果保留。客户和原录入人不变。" type="info" :closable="false" />
        <el-form label-position="top" :disabled="e.saving.value || e.uncertain.value" class="edit-form">
          <div class="edit-grid">
            <el-form-item label="跟进日期"><el-date-picker v-model="e.form.value.followup_date" class="edit-control" type="date" value-format="YYYY-MM-DD" /></el-form-item>
            <el-form-item label="沟通方式"><el-select v-model="e.form.value.channel" class="edit-control" clearable>
              <el-option v-for="v in channels" :key="v" :value="v" :label="v" />
            </el-select></el-form-item>
          </div>
          <el-form-item label="跟进原文"><el-input v-model="e.form.value.raw_text" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" maxlength="20000" /></el-form-item>
          <el-form-item label="摘要"><el-input v-model="e.form.value.summary" type="textarea" autosize maxlength="500" /></el-form-item>
          <el-form-item label="客户变化"><el-select v-model="e.form.value.state_changes" multiple clearable>
            <el-option v-for="v in states" :key="v" :value="v" :label="v" />
          </el-select></el-form-item>
          <section v-for="group in GROUPS" :key="group.kind" class="edit-items">
            <div class="edit-heading"><strong>{{ group.label }}</strong><GlassButton variant="link" left-icon="Plus" :disabled="frozen" @click="addItem(group.kind)">添加</GlassButton></div>
            <div v-for="item in e.form.value.items.filter(row => row.kind === group.kind)" :key="item.id || `new-${item.key}`" class="edit-item">
              <el-input v-model="item.text" type="textarea" autosize maxlength="1000" :aria-label="group.label" />
              <div v-if="item.kind !== 'content'" class="edit-item-meta">
                <el-select v-model="item.category" class="edit-category" placeholder="分类" clearable aria-label="分类">
                  <el-option v-for="v in categories" :key="v" :value="v" :label="v" />
                </el-select>
                <el-checkbox v-model="item.severity" true-value="紧急" false-value="一般">紧急</el-checkbox>
                <el-checkbox v-model="item.record_only" :disabled="!canToggleRecordOnly(item, e.record.value)">仅记录，不跟进</el-checkbox>
              </div>
              <GlassButton variant="link" left-icon="Delete" :disabled="frozen || !canRemoveEditItem(item, e.record.value)"
                           @click="e.form.value.items.splice(e.form.value.items.indexOf(item), 1)">删除</GlassButton>
              <span v-if="!canRemoveEditItem(item, e.record.value)" class="edit-hint">处理记录已产生，可更正内容，保留处理结果。</span>
            </div>
          </section>
          <el-form-item label="截图">
            <div class="edit-shots">
              <div v-for="id in e.form.value.attachment_ids" :key="id">
                {{ attachmentName(id) }} <GlassButton variant="link" :disabled="frozen" @click="e.form.value.attachment_ids.splice(e.form.value.attachment_ids.indexOf(id), 1)">移除</GlassButton>
              </div>
              <AppUpload :model-value="e.form.value.attachment_ids.map(id => ({ id }))" :show-list="false"
                         accept="image/png,image/jpeg,image/webp" :upload-fn="upload" :max-size-mb="10">
                <GlassButton :loading="uploading" :disabled="frozen || uploading || e.form.value.attachment_ids.length >= 9">添加截图</GlassButton>
              </AppUpload>
            </div>
          </el-form-item>
          <div class="edit-grid">
            <el-form-item label="下次跟进日期"><el-date-picker v-model="e.form.value.next_date" class="edit-control" type="date" value-format="YYYY-MM-DD" clearable /></el-form-item>
            <el-form-item label="下次沟通方式"><el-select v-model="e.form.value.next_method" class="edit-control" clearable>
              <el-option v-for="v in channels" :key="v" :value="v" :label="v" />
            </el-select></el-form-item>
          </div>
          <el-form-item label="下次计划"><el-input v-model="e.form.value.next_plan" type="textarea" autosize maxlength="500" /></el-form-item>
          <el-form-item label="修改原因" required><el-input v-model="e.form.value.reason" type="textarea" autosize maxlength="500" placeholder="说明本次更正内容" /></el-form-item>
        </el-form>
      </template>
    </div>
    <template #footer><div class="dialog-footer">
      <GlassButton :disabled="e.saving.value" @click="close">取消</GlassButton>
      <GlassButton v-permission="'domestic_followup:write'" variant="primary" :loading="e.saving.value"
                   :disabled="!e.form.value || e.conflict.value || uploading" @click="save">保存修改</GlassButton>
    </div></template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import GlassButton from '@/components/GlassButton.vue'
import AppUpload from '@/components/AppUpload.vue'
import { followupApi, apiError } from '@/api/domesticFollowup'
import { confirmAction, isFeedbackCancelled, msgError, msgSuccessText } from '@/utils/feedback'
import { canRemoveEditItem, canToggleRecordOnly } from '../followupEdit'
import { useFollowupEditor } from '../composables/useFollowupEditor'

const emit = defineEmits(['saved'])
const e = useFollowupEditor(followupApi, row => { msgSuccessText('跟进已修改，关联待办已同步'); emit('saved', row) })
const GROUPS = [{ kind: 'content', label: '跟进要点' }, { kind: 'issue', label: '异常' }, { kind: 'suggestion', label: '意见建议' }]
const uploading = ref(false), uploads = ref([])
const frozen = computed(() => e.saving.value || e.uncertain.value)
const channels = computed(() => [...new Set([...(e.dicts.value.domestic_followup_channel || []), e.form.value?.channel, e.form.value?.next_method].filter(Boolean))])
const categories = computed(() => e.dicts.value.domestic_followup_category || [])
const states = computed(() => [...new Set([...(e.dicts.value.domestic_followup_state_change || []), ...(e.form.value?.state_changes || [])])])
let itemKey = 0
function addItem(kind) {
  e.form.value.items.push({ kind, text: '', origin: 'user', severity: kind === 'content' ? null : '一般',
    category: null, record_only: false, key: ++itemKey })
}
function attachmentName(id) {
  return [...e.record.value.attachments, ...uploads.value].find(a => a.id === id)?.file_name || `截图 ${id}`
}
async function upload(file) {
  if (frozen.value || uploading.value || e.form.value.attachment_ids.length >= 9) throw new Error('当前不能继续上传')
  uploading.value = true
  try {
    const attachment = await followupApi.upload(file)
    uploads.value.push(attachment)
    e.form.value.attachment_ids.push(attachment.id)
    return attachment
  } catch (error) { msgError(apiError(error, '上传失败'), error); throw error }
  finally { uploading.value = false }
}
async function confirmDiscard() {
  if (!e.dirty.value) return true
  try { await confirmAction('放弃当前尚未保存的修改？', '放弃修改'); return true }
  catch (error) { if (!isFeedbackCancelled(error)) msgError('无法确认关闭', error); return false }
}
async function close() { if (!e.saving.value && !uploading.value && await confirmDiscard()) e.close() }
async function reload() { if (await confirmDiscard()) await e.reload() }
async function save() {
  await e.save()
}
function open(id) { uploads.value = []; return e.open(id) }
defineExpose({ open })
</script>

<style scoped>
.edit-form { margin-top: 20px; min-width: 0; }
.edit-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.edit-grid > * { min-width: 0; }
.edit-control { width: 100%; min-width: 0; }
.edit-heading, .edit-item-meta { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
.edit-heading { justify-content: space-between; }
.edit-items { margin-bottom: 20px; }
.edit-item { padding: 12px 0; border-bottom: 1px solid var(--border-color); }
.edit-item-meta { margin: 8px 0; }
.edit-category { width: 180px; }
.edit-hint { color: var(--text-secondary); font-size: 12px; }
.edit-shots { width: 100%; }
@media (max-width: 600px) { .edit-grid { grid-template-columns: 1fr; gap: 0; } }
</style>

<style>
.el-dialog.followup-edit-dialog {
  max-width: calc(100vw - 24px);
  max-height: calc(100dvh - 32px);
  margin: 16px auto;
  display: flex;
  flex-direction: column;
}
.followup-edit-dialog > .el-dialog__body { overflow-y: auto; min-height: 0; }
.followup-edit-dialog > .el-dialog__header, .followup-edit-dialog > .el-dialog__footer { flex-shrink: 0; }
.followup-edit-dialog .dialog-footer { display: flex; justify-content: flex-end; flex-wrap: wrap; gap: 10px; }
</style>
