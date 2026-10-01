<template>
  <el-dialog :model-value="dialog.open" :title="dialog.title" width="480" append-to-body @update:model-value="onToggle">
    <p v-if="dialog.message" class="tpd-message">{{ dialog.message }}</p>
    <el-input
      v-if="dialog.input"
      v-model="dialog.value"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 4 }"
      maxlength="500"
      :placeholder="dialog.placeholder"
      @keydown.enter.ctrl.prevent="confirm"
    />
    <p v-if="dialog.error" class="tpd-error" role="alert">{{ dialog.error }}</p>
    <template #footer>
      <GlassButton @click="cancel">取消</GlassButton>
      <GlassButton variant="primary" @click="confirm">{{ dialog.confirmText }}</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'
import { useTaskDialog } from '../composables/useTaskDialog'

const { dialog, confirm, cancel } = useTaskDialog()

function onToggle(open) {
  if (!open) cancel()
}
</script>

<style scoped>
.tpd-message { margin: 0 0 12px; font-size: 13.5px; line-height: 1.6; color: var(--text-secondary); white-space: pre-line; }
.tpd-error { margin: 8px 0 0; font-size: 12.5px; color: var(--color-danger-text); }
</style>
