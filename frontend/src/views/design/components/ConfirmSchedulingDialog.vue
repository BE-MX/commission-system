<template>
  <el-dialog :model-value="visible" title="确认排期" width="640px" :close-on-click-modal="false" @update:model-value="emit('update:visible', $event)">
    <el-form label-position="top" :model="form" class="confirm-form">
      <el-form-item label="客户"><span>{{ row?.customer_name }}</span></el-form-item>
      <el-form-item label="设计师" required>
        <el-select v-model="form.designer_id" placeholder="请选择设计师" class="full-width">
          <el-option v-for="designer in designers" :key="designer.id" :label="designer.name" :value="designer.id" />
        </el-select>
      </el-form-item>
      <el-form-item label="排期日期" required class="date-period-item">
        <DatePeriodPicker
          v-model:start-date="form.startDate"
          v-model:start-period="form.startPeriod"
          v-model:end-date="form.endDate"
          v-model:end-period="form.endPeriod"
        />
      </el-form-item>
      <el-form-item label="备注"><el-input v-model="form.comment" type="textarea" :rows="2" placeholder="选填" /></el-form-item>
      <el-form-item>
        <el-checkbox v-model="form.sync_unavailable">将当前排期日期同步设置为不可用</el-checkbox>
      </el-form-item>
    </el-form>
    <template #footer>
      <GlassButton variant="ghost" @click="emit('update:visible', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="saving" @click="emit('submit')">确认</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'
import DatePeriodPicker from '@/components/design/DatePeriodPicker.vue'

defineProps({ visible: Boolean, row: Object, form: Object, designers: Array, saving: Boolean })
const emit = defineEmits(['update:visible', 'submit'])
</script>

<style>
.confirm-form .full-width,
.confirm-form .date-period-item .el-date-editor,
.confirm-form .date-period-item .el-date-picker { width: 100%; }
</style>
