<template>
  <el-dialog :model-value="editDateVisible" title="修改期望日期" width="480px" :close-on-click-modal="false" @update:model-value="emit('update:editDateVisible', $event)">
    <el-form label-position="top">
      <el-form-item label="期望日期">
        <DatePeriodPicker
          v-model:start-date="editDateForm.startDate"
          v-model:start-period="editDateForm.startPeriod"
          v-model:end-date="editDateForm.endDate"
          v-model:end-period="editDateForm.endPeriod"
        />
      </el-form-item>
    </el-form>
    <template #footer>
      <GlassButton variant="ghost" @click="emit('update:editDateVisible', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="editDateSaving" @click="emit('submitEditDate')">保存</GlassButton>
    </template>
  </el-dialog>

  <el-dialog :model-value="remarkVisible" :title="remarkTarget === 'task' ? '修改排期备注' : '修改预约备注'" width="480px" :close-on-click-modal="false" :close-on-press-escape="!remarkSaving" :show-close="!remarkSaving" @update:model-value="emit('update:remarkVisible', $event)">
    <el-form label-position="top">
      <el-form-item label="备注"><el-input v-model="remarkForm.remark" type="textarea" :rows="4" placeholder="请输入备注" /></el-form-item>
    </el-form>
    <template #footer>
      <GlassButton variant="ghost" :disabled="remarkSaving" @click="emit('update:remarkVisible', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="remarkSaving" @click="emit('submitRemark')">保存</GlassButton>
    </template>
  </el-dialog>

  <el-dialog :model-value="editTaskDateVisible" title="修改排期日期" width="480px" :close-on-click-modal="false" @update:model-value="emit('update:editTaskDateVisible', $event)">
    <el-form label-position="top">
      <el-form-item label="排期日期">
        <DatePeriodPicker
          v-model:start-date="editTaskDateForm.startDate"
          v-model:start-period="editTaskDateForm.startPeriod"
          v-model:end-date="editTaskDateForm.endDate"
          v-model:end-period="editTaskDateForm.endPeriod"
        />
      </el-form-item>
      <el-form-item label="改期备注"><el-input v-model="editTaskDateForm.comment" type="textarea" :rows="2" placeholder="选填，将包含在钉钉通知中" /></el-form-item>
    </el-form>
    <template #footer>
      <GlassButton variant="ghost" @click="emit('update:editTaskDateVisible', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="editTaskDateSaving" @click="emit('submitEditTaskDate')">保存</GlassButton>
    </template>
  </el-dialog>

  <el-dialog :model-value="shootTypeVisible" title="修改拍摄类型" width="480px" :close-on-click-modal="false" @update:model-value="emit('update:shootTypeVisible', $event)">
    <el-form label-position="top">
      <el-form-item label="拍摄类型">
        <el-select v-model="shootTypeForm.shoot_type" multiple placeholder="请选择拍摄类型" class="full-width">
          <el-option v-for="(label, code) in shootTypeMap" :key="code" :label="label" :value="code" />
        </el-select>
      </el-form-item>
    </el-form>
    <template #footer>
      <GlassButton variant="ghost" @click="emit('update:shootTypeVisible', false)">取消</GlassButton>
      <GlassButton variant="primary" :loading="shootTypeSaving" @click="emit('submitShootType')">保存</GlassButton>
    </template>
  </el-dialog>
</template>

<script setup>
import GlassButton from '@/components/GlassButton.vue'
import DatePeriodPicker from '@/components/design/DatePeriodPicker.vue'

defineProps({
  editDateVisible: Boolean, editDateForm: Object, editDateSaving: Boolean,
  remarkVisible: Boolean, remarkTarget: String, remarkForm: Object, remarkSaving: Boolean,
  editTaskDateVisible: Boolean, editTaskDateForm: Object, editTaskDateSaving: Boolean,
  shootTypeVisible: Boolean, shootTypeForm: Object, shootTypeSaving: Boolean, shootTypeMap: Object,
})
const emit = defineEmits([
  'update:editDateVisible', 'submitEditDate',
  'update:remarkVisible', 'submitRemark',
  'update:editTaskDateVisible', 'submitEditTaskDate',
  'update:shootTypeVisible', 'submitShootType',
])
</script>

<style scoped>
.full-width { width: 100%; }
</style>
