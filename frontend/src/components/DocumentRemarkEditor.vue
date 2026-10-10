<template>
  <div :key="authorityKey" class="document-remark">
    <template v-if="editing">
      <el-input v-model="draft" type="textarea" :rows="3" :maxlength="maxLength" show-word-limit :disabled="saving" aria-label="编辑备注" />
      <p class="document-remark__hint">已同步单据的修改保存在方舟；未同步单据在后续同步时带入。</p>
      <p v-if="error" class="document-remark__error" role="alert">{{ error }}</p>
      <div class="document-remark__actions">
        <GlassButton v-permission="permission" variant="primary" :loading="saving" :disabled="disabled || !editable" @click="save">保存备注</GlassButton>
        <GlassButton :disabled="saving" @click="cancel">取消</GlassButton>
      </div>
    </template>
    <template v-else>
      <p class="document-remark__text">{{ document.remark || '暂无备注' }}</p>
      <el-button v-if="editable" v-permission="permission" link type="primary" :disabled="disabled" @click="start">编辑备注</el-button>
    </template>
  </div>
</template>
<script setup>
import GlassButton from '@/components/GlassButton.vue'
import { useDocumentRemark } from '@/composables/useDocumentRemark'
const props = defineProps({
  document: { type: Object, required: true },
  kind: { type: String, required: true },
  disabled: Boolean,
})
const emit = defineEmits(['updated', 'editing', 'saving'])
const { editing, saving, draft, error, permission, maxLength, editable, authorityKey, start, save, cancel } = useDocumentRemark(props, emit)
</script>
<style scoped>
.document-remark__text { margin: 0 0 6px; white-space: pre-wrap; overflow-wrap: anywhere; }
.document-remark__hint { color: var(--text-secondary); font-size: 12px; }
.document-remark__error { color: var(--color-danger-text); font-size: 13px; }
.document-remark__actions { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
</style>
