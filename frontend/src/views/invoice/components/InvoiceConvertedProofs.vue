<template>
  <div class="converted-proofs">
    <el-form-item v-if="receipt" label="回款备注">
      <DocumentRemarkEditor :document="receipt" kind="receipt"
        :disabled="locked || loading || saving || uploading || changed"
        @editing="value => { remarkEditing = value; $emit('remark-editing', value) }"
        @saving="value => { remarkSaving = value; $emit('remark-saving', value) }"
        @updated="remarkUpdated" />
    </el-form-item>
    <p class="proof-note">截图可在这里移除或重新上传；至少保留一张，点击保存后生效。</p>
    <ReceiptProofs v-model="attachmentIds" :readonly="locked || loading || saving || remarkEditing || remarkSaving || version == null" @uploading="onUploading" />
    <p v-if="error" class="proof-error" role="alert">{{ error }}</p>
    <div class="proof-actions">
      <el-button :disabled="locked || loading || saving || uploading || remarkEditing || remarkSaving" @click="load">重新加载</el-button>
      <el-button type="primary" :loading="saving" :disabled="locked || loading || uploading || remarkEditing || remarkSaving || !changed" @click="save">保存截图变更</el-button>
    </div>
  </div>
</template>

<script setup>import { msgSuccessText } from '@/utils/feedback'
import { computed, onBeforeUnmount, ref, watch } from 'vue'

import { getReceipt, updateReceiptProofs } from '@/api/receipt'
import ReceiptProofs from '@/views/receipt/ReceiptProofs.vue'
import DocumentRemarkEditor from '@/components/DocumentRemarkEditor.vue'

const props = defineProps({ receiptId: { type: Number, required: true }, locked: Boolean })
const emit = defineEmits(['saved', 'uploading', 'dirty', 'updated', 'remark-editing', 'remark-saving'])
const receipt = ref(null), remarkEditing = ref(false), remarkSaving = ref(false)
const attachmentIds = ref([])
const savedIds = ref([])
const version = ref(null)
const loading = ref(false)
const saving = ref(false)
const uploading = ref(false)
const error = ref('')
const changed = computed(() => JSON.stringify(attachmentIds.value) !== JSON.stringify(savedIds.value))
let loadSequence = 0
let disposed = false

function onUploading(value) {
  uploading.value = value
  emit('uploading', value)
}

function remarkUpdated(row) {
  if (disposed || row.id !== props.receiptId) return
  receipt.value = row
  version.value = row.version
  emit('updated', row)
}

async function load() {
  if (props.locked || uploading.value || saving.value || remarkEditing.value || remarkSaving.value) return
  const sequence = ++loadSequence
  const receiptId = props.receiptId
  loading.value = true
  error.value = ''
  try {
    const row = await getReceipt(receiptId)
    if (disposed || sequence !== loadSequence || receiptId !== props.receiptId) return
    savedIds.value = row.attachments.map(file => file.id)
    attachmentIds.value = [...savedIds.value]
    version.value = row.version
    receipt.value = row
    emit('updated', row)
  } catch (e) {
    if (!disposed && sequence === loadSequence && receiptId === props.receiptId) error.value = e.response?.data?.detail || '回款截图加载失败，请重新加载'
  } finally {
    if (!disposed && sequence === loadSequence && receiptId === props.receiptId) loading.value = false
  }
}

async function save() {
  if (props.locked || saving.value || uploading.value || remarkEditing.value || remarkSaving.value || !changed.value) return
  if (!attachmentIds.value.length) {
    error.value = '请先重新上传截图；回款单至少保留一张凭证'
    return
  }
  saving.value = true
  error.value = ''
  const receiptId = props.receiptId
  try {
    const row = await updateReceiptProofs(receiptId, {
      version: version.value, attachment_ids: [...attachmentIds.value],
    })
    if (disposed || receiptId !== props.receiptId) return
    savedIds.value = row.attachments.map(file => file.id)
    attachmentIds.value = [...savedIds.value]
    version.value = row.version
    receipt.value = row
    emit('saved', receiptId, [...savedIds.value])
    emit('updated', row)
    msgSuccessText('回款截图已更新')
  } catch (e) {
    if (!disposed && receiptId === props.receiptId) error.value = e.response?.data?.detail || '截图保存失败，请重试'
  } finally {
    if (!disposed && receiptId === props.receiptId) saving.value = false
  }
}

watch(() => props.receiptId, () => { loadSequence += 1; receipt.value = null; attachmentIds.value = []; savedIds.value = []; version.value = null; load() }, { immediate: true })
watch(() => props.locked, locked => { if (!locked && version.value == null) load() })
watch(changed, value => emit('dirty', value), { immediate: true })
onBeforeUnmount(() => {
  disposed = true; loadSequence += 1
  emit('remark-editing', false); emit('remark-saving', false)
})
</script>

<style scoped>
.proof-note { margin: 0 0 8px; font-size: 12px; color: var(--text-secondary); }
.proof-error { color: var(--color-danger-text); font-size: 12px; }
.proof-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: 10px; }
</style>
