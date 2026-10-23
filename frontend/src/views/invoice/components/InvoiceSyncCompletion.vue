<template>
  <el-dialog
    :model-value="Boolean(message)"
    title="保存并同步完成"
    width="480px"
    class="invoice-sync-completion"
    align-center
    :show-close="false"
    :close-on-press-escape="false"
    :close-on-click-modal="true"
    append-to-body
    @update:model-value="value => { if (!value) $emit('dismiss') }"
  >
    <el-result icon="success" sub-title="点击提示框外的页面继续">
      <template #title><p class="completion-message">{{ message }}</p></template>
    </el-result>
  </el-dialog>
</template>

<script setup>
defineProps({ message: { type: String, default: '' } })
defineEmits(['dismiss'])
</script>

<style scoped>
.completion-message { overflow-wrap: anywhere; }
</style>
