<template>
  <el-form-item label="检验要求" required>
    <el-radio-group
      :model-value="inspectionRequirement(form)"
      aria-label="检验要求"
      @update:model-value="form.inspection_requirement = $event"
    >
      <el-radio value="single">单张检验照片</el-radio>
      <el-radio value="detail">明细检验照片</el-radio>
    </el-radio-group>
  </el-form-item>
</template>

<script setup>
import { inspectionRequirement } from '../composables/invoiceEditorState'

defineProps({ form: { type: Object, required: true } })
</script>
